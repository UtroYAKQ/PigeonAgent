"""e2b 兼容沙箱的进程内池：生命周期按「沙箱回收策略」执行。

- 按需创建：第一次真正调用沙箱工具时才建连，纯聊天轮次不启动沙箱。
- 正常执行中：保持 active，每次工具活动刷新计时；超时无动静 → kill。
- 本轮正常结束 / 等待 resume：pause 保活，同一会话下一轮 connect 复用；超时 → kill。
- 失败 / 取消：立即 kill，避免复用脏沙箱。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import Settings
from app.sandbox.workspace import connect_sandbox, create_sandbox, sandbox_ttl

if TYPE_CHECKING:
    from e2b import AsyncSandbox
else:  # pragma: no cover
    AsyncSandbox = Any

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    sandbox: AsyncSandbox
    sandbox_id: str
    last_touch: float = field(default_factory=time.monotonic)
    paused: bool = False
    run_id: str | None = None
    # 正在被 run 使用时巡检不能回收
    in_use: bool = False


class SandboxPool:
    """按会话独占的沙箱池：多轮 run 复用，中断时挂起，跑完立即回收。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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
        await asyncio.gather(
            *(self._kill_entry(entry) for entry in list(self._entries.values())),
            return_exceptions=True,
        )
        self._entries.clear()
        self._session_locks.clear()

    # ------------------------------------------------------------------ 对外动作
    async def acquire(self, session_id: UUID, run_id: str) -> AsyncSandbox:
        """拿到本轮要用的沙箱：有就 connect 复用，断线/被回收就兜底重建。"""
        async with self._lock_for(session_id):
            entry = self._entries.get(session_id)
            settings = self.settings
            if entry is not None:
                entry.in_use = True
                entry.last_touch = time.monotonic()
                try:
                    if entry.paused:
                        started = time.monotonic()
                        try:
                            entry.sandbox = await connect_sandbox(settings, entry.sandbox_id)
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
                            entry.sandbox = await create_sandbox(settings)
                            entry.sandbox_id = entry.sandbox.sandbox_id
                        entry.paused = False
                    else:
                        # 保活中的容器也要续期：上游 TTL 从创建起算，不续期到点就杀
                        set_timeout = getattr(entry.sandbox, "set_timeout", None)
                        if callable(set_timeout):
                            try:
                                await set_timeout(sandbox_ttl(settings))
                            except Exception:
                                logger.info(
                                    "Failed to renew timeout for sandbox %s", entry.sandbox_id
                                )
                except Exception:
                    entry.in_use = False
                    raise
            else:
                started = time.monotonic()
                sandbox = await create_sandbox(settings)
                logger.info(
                    "Sandbox %s created in %.2fs for session %s",
                    sandbox.sandbox_id,
                    time.monotonic() - started,
                    session_id,
                )
                entry = _Entry(
                    sandbox=sandbox,
                    sandbox_id=sandbox.sandbox_id,
                    run_id=run_id,
                    in_use=True,
                )
                self._entries[session_id] = entry
            entry.run_id = run_id
            return entry.sandbox

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

    async def discard(self, session_id: UUID) -> None:
        """失败/取消的 run：立即回收，避免复用脏沙箱。"""
        # 必须持锁：不持锁时并发的 acquire 会看到"没有 entry"再建一个，
        # 先建的那个没人 kill，就成了永不回收的孤儿容器。
        async with self._lock_for(session_id):
            entry = self._entries.pop(session_id, None)
            if entry is not None:
                entry.in_use = False
                await self._kill_entry(entry)

    # ------------------------------------------------------------------ 内部
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
            cutoff = time.monotonic() - self.settings.sandbox_idle_seconds
            stale = [
                key
                for key, entry in self._entries.items()
                if not entry.in_use and entry.last_touch < cutoff
            ]
            for session_id in stale:
                # 同样要在会话锁里做：巡检和新一轮 acquire 撞上是常态
                async with self._lock_for(session_id):
                    entry = self._entries.get(session_id)
                    if entry is None or entry.in_use:
                        # 等锁的这段时间里新一轮已经把沙箱接走了
                        continue
                    self._entries.pop(session_id)
                    logger.info("Sandbox %s idle timeout; killing", entry.sandbox_id)
                    await self._kill_entry(entry)
