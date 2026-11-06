"""e2b 兼容沙箱的进程内池：生命周期按「沙箱回收策略」执行。

- 按需创建：第一次真正调用沙箱工具时才建连，纯聊天轮次不启动沙箱。
- 正常执行中：保持 active，每次工具活动刷新计时；超时无动静 → kill。
- 本轮正常结束 / 等待 resume：pause 保活，同一会话下一轮 connect 复用；超时 → kill。
- 失败 / 取消：立即 kill，避免复用脏沙箱。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.core.config import Settings
from app.sandbox.workspace import connect_sandbox, create_sandbox, sandbox_ttl

if TYPE_CHECKING:
    from e2b import AsyncSandbox
else:  # pragma: no cover
    AsyncSandbox = Any

logger = logging.getLogger(__name__)

# 共享指针读写不能无限等：Redis 黑洞时让工具调用尽快失败/降级
REMOTE_TIMEOUT_SECONDS = 2.0


@dataclass
class _Entry:
    sandbox: AsyncSandbox
    sandbox_id: str
    last_touch: float = field(default_factory=time.monotonic)
    paused: bool = False
    run_id: str | None = None
    # 正在被 run 使用时巡检不能回收
    in_use: bool = False


@dataclass
class _RemoteEntry:
    """Redis 里共享的沙箱指针；物理沙箱在远端，任何 worker 都能 connect。"""

    sandbox_id: str
    paused: bool = False
    in_use: bool = False
    worker_id: str = ""


class SandboxPool:
    """按会话独占的沙箱池：多轮 run 复用，中断时挂起，跑完立即回收。

    配置 Redis 后，沙箱指针（而不是 sandbox 对象）跨 worker 共享：run 被调度到
    另一个进程时可以直接 connect 同一个远端沙箱，工作区文件不会丢。
    """

    def __init__(self, settings: Settings, *, redis_client: Redis | None = None) -> None:
        self.settings = settings
        self.worker_id = uuid4().hex
        self._redis = redis_client
        self._owns_redis = False
        if self._redis is None:
            redis_url = getattr(settings, "redis_url", None)
            if redis_url:
                self._redis = Redis.from_url(
                    redis_url, socket_connect_timeout=3, health_check_interval=30
                )
                self._owns_redis = True
        self._entries: dict[UUID, _Entry] = {}
        # 每个会话一把锁：建连/重连放进锁里，但不同会话之间不再互相阻塞
        self._session_locks: dict[UUID, asyncio.Lock] = {}
        self._sweeper: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ 生命周期
    def configure(self, settings: Settings) -> None:
        """配置表更新后，让下一次建连/巡检用上新的凭证与回收参数。"""
        self.settings = settings

    def start(self) -> None:
        self._sweeper = asyncio.create_task(self._sweep_loop())

    def _sweep_interval(self) -> float:
        return min(30.0, max(self.settings.sandbox_idle_seconds / 4, 1.0))

    async def aclose(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        for session_id, entry in list(self._entries.items()):
            remote = await self._remote_get_safe(session_id)
            if self._remote_owned_by_other(remote):
                # 已被别的 worker 接管（例如本进程刚重启过），不要误杀共享沙箱
                if remote is not None and remote.sandbox_id != entry.sandbox_id:
                    await self._kill_entry(entry)
                continue
            await self._kill_entry(entry)
            await self._remote_delete(session_id)
        self._entries.clear()
        self._session_locks.clear()
        if self._owns_redis and self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()

    # ------------------------------------------------------------------ 对外动作
    async def acquire(self, session_id: UUID, run_id: str) -> AsyncSandbox:
        """拿到本轮要用的沙箱：本地/远端有就 connect 复用，断线/被回收就兜底重建。"""
        async with self._lock_for(session_id):
            entry = self._entries.get(session_id)
            remote = await self._remote_get_safe(session_id)
            if entry is not None and remote is not None and self._remote_owned_by_other(remote):
                # 本地引用已过时：另一个 worker 接管了同一会话的沙箱，不能 kill 它
                logger.info(
                    "Sandbox %s for session %s moved to worker %s; dropping local handle",
                    entry.sandbox_id,
                    session_id,
                    remote.worker_id,
                )
                self._entries.pop(session_id, None)
                if remote.sandbox_id != entry.sandbox_id:
                    # 远端已经指向另一个沙箱，本地这个没人用了，顺手回收
                    await self._kill_entry(entry)
                entry = None
            elif entry is not None and remote is not None and remote.worker_id == self.worker_id:
                # 以 Redis 里的状态为准，进程重启或跨轮释放后本地字段可能落后
                entry.paused = remote.paused
            if entry is None and remote is not None:
                entry = await self._connect_remote(session_id, remote)
            if entry is None:
                entry = await self._create_entry(session_id)
            else:
                await self._prepare_entry(entry, session_id)
            entry.in_use = True
            entry.run_id = run_id
            entry.last_touch = time.monotonic()
            await self._remote_save(session_id, entry)
            return entry.sandbox

    async def _connect_remote(self, session_id: UUID, remote: _RemoteEntry) -> _Entry | None:
        if remote.in_use and self._remote_owned_by_other(remote):
            # 另一个 worker 正在用这个沙箱；本次租约虽然到手，也不共享容器，
            # 新建一个隔离沙箱，旧沙箱由原 worker 收尾或上游 TTL 回收。
            logger.warning(
                "Sandbox %s for session %s is in use by worker %s; creating an isolated one",
                remote.sandbox_id,
                session_id,
                remote.worker_id,
            )
            return None
        started = time.monotonic()
        try:
            sandbox = await connect_sandbox(self.settings, remote.sandbox_id)
        except Exception:
            logger.info(
                "Sandbox %s for session %s is gone; recreating",
                remote.sandbox_id,
                session_id,
            )
            await self._remote_delete(session_id)
            return None
        logger.info(
            "Sandbox %s resumed in %.2fs for session %s on this worker",
            remote.sandbox_id,
            time.monotonic() - started,
            session_id,
        )
        entry = _Entry(sandbox=sandbox, sandbox_id=sandbox.sandbox_id, paused=False)
        self._entries[session_id] = entry
        return entry

    async def _create_entry(self, session_id: UUID) -> _Entry:
        started = time.monotonic()
        sandbox = await create_sandbox(self.settings)
        logger.info(
            "Sandbox %s created in %.2fs for session %s",
            sandbox.sandbox_id,
            time.monotonic() - started,
            session_id,
        )
        entry = _Entry(sandbox=sandbox, sandbox_id=sandbox.sandbox_id)
        self._entries[session_id] = entry
        return entry

    async def _prepare_entry(self, entry: _Entry, session_id: UUID) -> None:
        if entry.paused:
            started = time.monotonic()
            try:
                entry.sandbox = await connect_sandbox(self.settings, entry.sandbox_id)
                logger.info(
                    "Sandbox %s resumed in %.2fs for session %s",
                    entry.sandbox_id,
                    time.monotonic() - started,
                    session_id,
                )
            except Exception:
                logger.info(
                    "Sandbox %s for session %s is gone; recreating",
                    entry.sandbox_id,
                    session_id,
                )
                sandbox = await create_sandbox(self.settings)
                entry.sandbox = sandbox
                entry.sandbox_id = sandbox.sandbox_id
            entry.paused = False
            return
        # 保活中的容器也要续期：上游 TTL 从创建起算，不续期到点就杀
        set_timeout = getattr(entry.sandbox, "set_timeout", None)
        if callable(set_timeout):
            try:
                await set_timeout(sandbox_ttl(self.settings))
            except Exception:
                logger.info("Failed to renew timeout for sandbox %s", entry.sandbox_id)

    def touch(self, session_id: UUID) -> None:
        entry = self._entries.get(session_id)
        if entry is not None:
            entry.last_touch = time.monotonic()

    async def release(self, session_id: UUID) -> None:
        """本轮结束/等待 resume：能挂起就挂起，挂不起就原地保活，空闲超时后由 sweeper 回收。"""
        async with self._lock_for(session_id):
            entry = self._entries.get(session_id)
            if entry is None:
                return
            remote = await self._remote_get_safe(session_id)
            if remote is not None and self._remote_owned_by_other(remote):
                self._entries.pop(session_id, None)
                if remote.sandbox_id != entry.sandbox_id:
                    await self._kill_entry(entry)
                return
            paused = False
            pause = getattr(entry.sandbox, "beta_pause", None)
            if callable(pause):
                try:
                    await pause()
                    paused = True
                except Exception:
                    # 阿里云 e2b 网关明确不支持 pause（pauseSession is not enabled）；
                    # 这时不能假装它挂起了，否则下一轮会走「重连已暂停容器」的分支
                    logger.info(
                        "Sandbox %s does not support pause; keeping it warm", entry.sandbox_id
                    )
            entry.paused = paused
            entry.in_use = False
            # 从本轮结束开始重新计算空闲时间，复用窗口给满
            entry.last_touch = time.monotonic()
            await self._remote_save(session_id, entry)

    async def discard(self, session_id: UUID) -> None:
        """失败/取消的 run：立即回收，避免复用脏沙箱。"""
        # 必须持锁：不持锁时并发的 acquire 会看到"没有 entry"再建一个，
        # 先建的那个没人 kill，就成了永不回收的孤儿容器。
        async with self._lock_for(session_id):
            entry = self._entries.pop(session_id, None)
            if entry is not None:
                remote = await self._remote_get_safe(session_id)
                if remote is not None and self._remote_owned_by_other(remote):
                    # 本地只是过时引用；远端指向同一个沙箱时不能杀，指向旧沙箱时顺手回收
                    if remote.sandbox_id != entry.sandbox_id:
                        await self._kill_entry(entry)
                    return
                entry.in_use = False
                await self._kill_entry(entry)
                await self._remote_delete(session_id)

    # ------------------------------------------------------------------ 内部
    def _remote_owned_by_other(self, remote: _RemoteEntry | None) -> bool:
        return remote is not None and bool(remote.worker_id) and remote.worker_id != self.worker_id

    def _lock_for(self, session_id: UUID) -> asyncio.Lock:
        """每个会话一把锁；锁对象留着不删——删它会让两个并发 acquire 各拿一把新锁。"""
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    async def _kill_entry(self, entry: _Entry) -> None:
        kill = getattr(entry.sandbox, "kill", None)
        if not callable(kill):
            return
        try:
            await kill()
        except Exception:
            logger.info("Failed to kill sandbox %s", entry.sandbox_id, exc_info=True)

    async def _sweep_loop(self) -> None:
        while True:
            # configure() 更新空闲秒数后，巡检频率下一轮就跟上
            await asyncio.sleep(self._sweep_interval())
            try:
                await self._sweep_once()
            except Exception:
                logger.exception("Sandbox sweep failed; will retry next interval")

    async def _sweep_once(self) -> None:
        cutoff = time.monotonic() - self.settings.sandbox_idle_seconds
        for session_id, entry in list(self._entries.items()):
            if entry.in_use:
                async with self._lock_for(session_id):
                    current = self._entries.get(session_id)
                    if current is None or not current.in_use:
                        continue
                    try:
                        remote = await self._remote_get_checked(session_id)
                    except Exception:
                        logger.exception(
                            "Skipping sandbox sweep for session %s; registry unavailable",
                            session_id,
                        )
                        continue
                    if self._remote_owned_by_other(remote):
                        # 本 run 正在用本地沙箱，不能在这里杀；远端由持有者收尾
                        continue
                    # 使用中持续续期，避免上游 TTL 或共享指针先到期
                    await self._remote_save(session_id, current)
                continue
            if entry.last_touch >= cutoff:
                continue
            # 同样要在会话锁里做：巡检和新一轮 acquire 撞上是常态
            async with self._lock_for(session_id):
                current = self._entries.get(session_id)
                if current is None or current.in_use:
                    # 等锁的这段时间里新一轮已经把沙箱接走了
                    continue
                try:
                    remote = await self._remote_get_checked(session_id)
                except Exception:
                    logger.exception(
                        "Skipping sandbox sweep for session %s; registry unavailable",
                        session_id,
                    )
                    continue
                if remote is not None and (self._remote_owned_by_other(remote) or remote.in_use):
                    logger.info(
                        "Dropping local sandbox %s for session %s; another worker owns it",
                        current.sandbox_id,
                        session_id,
                    )
                    self._entries.pop(session_id, None)
                    if remote.sandbox_id != current.sandbox_id:
                        await self._kill_entry(current)
                    continue
                self._entries.pop(session_id, None)
                logger.info("Sandbox %s idle timeout; killing", current.sandbox_id)
                await self._kill_entry(current)
                await self._remote_delete(session_id)

    # ------------------------------------------------------------------ Redis 指针
    def _remote_key(self, session_id: UUID) -> str:
        return f"pigeon:sandbox:{session_id}"

    async def _remote_get_safe(self, session_id: UUID) -> _RemoteEntry | None:
        if self._redis is None:
            return None
        try:
            return await self._remote_get(session_id)
        except Exception:
            logger.exception("Failed to read sandbox registry for session %s", session_id)
            return None

    async def _remote_get_checked(self, session_id: UUID) -> _RemoteEntry | None:
        """巡检用：Redis 不可用时让异常冒出来，宁可跳过这轮也不误杀共享沙箱。"""
        if self._redis is None:
            return None
        return await self._remote_get(session_id)

    async def _remote_get(self, session_id: UUID) -> _RemoteEntry | None:
        assert self._redis is not None
        async with asyncio.timeout(REMOTE_TIMEOUT_SECONDS):
            raw = await self._redis.get(self._remote_key(session_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return None
            sandbox_id = data.get("sandbox_id")
            if not isinstance(sandbox_id, str) or not sandbox_id:
                return None
            return _RemoteEntry(
                sandbox_id=sandbox_id,
                paused=bool(data.get("paused", False)),
                in_use=bool(data.get("in_use", False)),
                worker_id=str(data.get("worker_id") or ""),
            )
        except (TypeError, ValueError):
            logger.warning("Ignoring malformed sandbox registry entry for session %s", session_id)
            return None

    async def _remote_save(self, session_id: UUID, entry: _Entry) -> None:
        if self._redis is None:
            return
        payload = json.dumps(
            {
                "sandbox_id": entry.sandbox_id,
                "paused": entry.paused,
                "in_use": entry.in_use,
                "worker_id": self.worker_id,
            }
        )
        try:
            async with asyncio.timeout(REMOTE_TIMEOUT_SECONDS):
                await self._redis.set(
                    self._remote_key(session_id),
                    payload,
                    ex=max(sandbox_ttl(self.settings), 60),
                )
        except Exception:
            logger.exception("Failed to save sandbox registry for session %s", session_id)

    async def _remote_delete(self, session_id: UUID) -> None:
        if self._redis is None:
            return
        try:
            async with asyncio.timeout(REMOTE_TIMEOUT_SECONDS):
                await self._redis.delete(self._remote_key(session_id))
        except Exception:
            logger.exception("Failed to delete sandbox registry for session %s", session_id)
