"""跨 worker 的 run 控制：Redis 归属键 + Pub/Sub 取消广播。

单进程时取消令牌就在本地 dict 里；配置 Redis 后，run 可能落在任意 worker，
取消请求也可能落到另一个 worker。归属键回答“这条 run 还活着吗”，Pub/Sub
负责把取消意图送到实际持有令牌的进程。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 归属键和取消标记的兜底 TTL；run 期间由心跳续期，worker 崩溃后不会永久留脏键
OWNER_TTL_SECONDS = 1_200
# 控制面命令不能无限等：Redis 黑洞时让取消请求尽快失败，而不是挂住 HTTP 请求
COMMAND_TIMEOUT_SECONDS = 2.0


class RunControl:
    def __init__(
        self,
        redis_client: Redis,
        *,
        key_prefix: str = "pigeon",
        owns_redis: bool = False,
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._channel = f"{key_prefix}:run-control:cancel"
        self._owns_redis = owns_redis
        self._on_cancel: Callable[[str, UUID], None] | None = None
        self._on_ready: Callable[[], Awaitable[None]] | None = None
        self._listener: asyncio.Task[None] | None = None
        self._pubsub: Any = None
        self._closed = False
        self._ready = asyncio.Event()

    def set_handler(self, handler: Callable[[str, UUID], None]) -> None:
        self._on_cancel = handler

    def set_ready_handler(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._on_ready = handler

    async def start(self) -> None:
        if self._listener is None and not self._closed:
            self._listener = asyncio.create_task(self._listen(), name="run-control")

    async def wait_ready(self, seconds: float = 2.0) -> None:
        """测试和启动探活用：等 Pub/Sub 订阅真正建立，避免刚 publish 就被丢。"""
        async with asyncio.timeout(seconds):
            await self._ready.wait()

    async def aclose(self) -> None:
        self._closed = True
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        pubsub, self._pubsub = self._pubsub, None
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.aclose()
        if self._owns_redis:
            with contextlib.suppress(Exception):
                await self._redis.aclose()

    async def register(self, run_id: str, session_id: UUID) -> None:
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
                await self._redis.set(
                    self._owner_key(run_id), str(session_id), ex=OWNER_TTL_SECONDS
                )
        except Exception:
            # 取消总线不可用时 run 仍要继续；只损失跨 worker 取消这一条兜底
            logger.exception("Failed to register run control owner for %s", run_id)

    async def unregister(self, run_id: str) -> None:
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
                await self._redis.delete(self._owner_key(run_id), self._cancel_key(run_id))
        except Exception:
            logger.exception("Failed to remove run control owner for %s", run_id)

    async def touch(self, run_id: str, session_id: UUID) -> None:
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
                # 用 set 而不是 expire：Redis 重启丢键后，心跳能把归属标记补回来
                await self._redis.set(
                    self._owner_key(run_id), str(session_id), ex=OWNER_TTL_SECONDS
                )
        except Exception:
            logger.exception("Failed to refresh run control owner for %s", run_id)

    async def request_cancel(self, session_id: UUID, run_id: str) -> bool:
        async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
            owner = await self._redis.get(self._owner_key(run_id))
            if owner is None or _as_text(owner) != str(session_id):
                return False
            # 先落标记再广播：listener 正断线重连时，恢复后还能从标记里补取消
            await self._redis.set(self._cancel_key(run_id), "1", ex=OWNER_TTL_SECONDS)
            await self._redis.publish(
                self._channel,
                json.dumps({"run_id": run_id, "session_id": str(session_id)}),
            )
            return True

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
            return bool(await self._redis.exists(self._cancel_key(run_id)))

    def _owner_key(self, run_id: str) -> str:
        return f"{self._prefix}:run-control:owner:{run_id}"

    def _cancel_key(self, run_id: str) -> str:
        return f"{self._prefix}:run-control:cancel:{run_id}"

    async def _listen(self) -> None:
        while not self._closed:
            try:
                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(self._channel)
                self._ready.set()
                await self._notify_ready()
                async for raw in self._pubsub.listen():
                    if raw.get("type") == "message":
                        self._dispatch(raw.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Run control listener failed; retrying")
                await asyncio.sleep(1)
            finally:
                pubsub, self._pubsub = self._pubsub, None
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()

    def _dispatch(self, raw: Any) -> None:
        try:
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            data = json.loads(text)
            run_id = str(data["run_id"])
            session_id = UUID(str(data["session_id"]))
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring malformed run control message: %r", raw)
            return
        if self._on_cancel is not None:
            self._on_cancel(run_id, session_id)

    async def _notify_ready(self) -> None:
        if self._on_ready is None:
            return
        try:
            await self._on_ready()
        except Exception:
            logger.exception("Run control ready handler failed")


def _as_text(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value
