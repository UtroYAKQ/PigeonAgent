from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from redis.asyncio import Redis

from app.core.exceptions import ConflictError, NotFoundError
from app.render.producer import RenderProducer
from app.render.queue import MAX_BACKLOG, RenderCursorInvalid, RenderQueue, RenderStream
from app.render.redis_queue import RedisRenderQueue

if TYPE_CHECKING:
    from app.render.consumer import RenderConsumer

logger = logging.getLogger(__name__)

# 活跃 run 标记的兜底 TTL：正常路径 close 时会显式删除；
# 进程硬崩后靠它自动解除互斥，不必等人工清理
ACTIVE_RUN_TTL_SECONDS = 3_600
CANCEL_REQUEST_TTL_SECONDS = 3_600


class RenderHub:
    """运行队列注册表：每个 session 同时只允许一个活跃运行。

    配了 Redis 时注册表与事件流都放在 Redis 里，多 worker 各自的进程
    看到同一份状态；没配就退回进程内 dict，单 worker 部署零依赖。
    """

    def __init__(
        self,
        *,
        max_backlog: int = MAX_BACKLOG,
        redis_client: Redis | None = None,
        key_prefix: str = "pigeon",
        retain_seconds: int = 600,
    ) -> None:
        self._max_backlog = max_backlog
        self._redis = redis_client
        self._prefix = key_prefix
        self._retain = retain_seconds
        self._queues: dict[str, RenderStream] = {}
        self._active: dict[UUID, str] = {}
        self._owners: dict[str, UUID] = {}

    @property
    def distributed(self) -> bool:
        return self._redis is not None

    async def create(self, session_id: UUID, run_id: str) -> RenderProducer:
        if self._redis is None:
            if run_id in self._queues:
                raise ConflictError(f"Run {run_id} is already streaming")
            if session_id in self._active:
                raise ConflictError(
                    f"Session {session_id} already has an active run",
                    active_run_id=self._active[session_id],
                )
            queue = RenderQueue(run_id, max_backlog=self._max_backlog)
            self._queues[run_id] = queue
            self._owners[run_id] = session_id
            self._active[session_id] = run_id
            return RenderProducer(self, session_id, queue)

        owner_key = self._key(f"owner:{run_id}")
        claimed = await self._redis.set(
            owner_key, str(session_id), nx=True, ex=ACTIVE_RUN_TTL_SECONDS
        )
        if not claimed:
            raise ConflictError(f"Run {run_id} is already streaming")
        active_key = self._key(f"active:{session_id}")
        acquired = await self._redis.set(active_key, run_id, nx=True, ex=ACTIVE_RUN_TTL_SECONDS)
        if not acquired:
            await self._redis.delete(owner_key)
            current = await self._redis.get(active_key)
            raise ConflictError(
                f"Session {session_id} already has an active run",
                active_run_id=_as_text(current),
            )
        return RenderProducer(
            self,
            session_id,
            RedisRenderQueue(
                self._redis, run_id, key_prefix=self._prefix, retain_seconds=self._retain
            ),
        )

    async def subscribe(
        self, run_id: str, after: int = 0, *, session_id: UUID | None = None
    ) -> RenderConsumer | None:
        queue = await self._live_queue(run_id, session_id)
        if queue is None:
            return None
        last = await queue.last_seq()
        if not 0 <= after <= last:
            raise RenderCursorInvalid(f"Event cursor {after} is out of range")
        return queue.consumer(after)

    async def _live_queue(self, run_id: str, session_id: UUID | None) -> RenderStream | None:
        """run 在注册表里且归属匹配时，返回它的队列；否则 None（SSE 端点回 410）。"""
        if self._redis is not None:
            owner = await self._redis.get(self._key(f"owner:{run_id}"))
            if owner is None:
                return None
            owner_id: UUID | None = _as_uuid(owner)
            queue: RenderStream | None = RedisRenderQueue(
                self._redis, run_id, key_prefix=self._prefix, retain_seconds=self._retain
            )
        else:
            owner_id = self._owners.get(run_id)
            queue = self._queues.get(run_id)
        if owner_id is None or queue is None:
            return None
        if session_id is not None and owner_id != session_id:
            raise NotFoundError(f"Run {run_id} does not belong to session {session_id}")
        return queue

    async def finish(self, session_id: UUID, run_id: str) -> None:
        if self._redis is None:
            self._queues.pop(run_id, None)
            self._owners.pop(run_id, None)
            if self._active.get(session_id) == run_id:
                del self._active[session_id]
            return
        active_key = self._key(f"active:{session_id}")
        current = await self._redis.get(active_key)
        if _as_text(current) == run_id:
            await self._redis.delete(active_key)
        await self._redis.delete(
            self._key(f"owner:{run_id}"),
            self._key(f"cancel:{run_id}"),
        )

    async def renew(self, session_id: UUID, run_id: str) -> bool:
        """只给仍属于本 run 的 Redis 元数据续租，防止旧 worker 刷新新 run。"""
        if self._redis is None:
            return self._active.get(session_id) == run_id and self._owners.get(run_id) == session_id
        owner_key = self._key(f"owner:{run_id}")
        active_key = self._key(f"active:{session_id}")
        owner, active = await self._redis.mget(owner_key, active_key)
        if _as_text(owner) != str(session_id) or _as_text(active) != run_id:
            return False
        pipe = self._redis.pipeline(transaction=True)
        pipe.expire(owner_key, ACTIVE_RUN_TTL_SECONDS)
        pipe.expire(active_key, ACTIVE_RUN_TTL_SECONDS)
        await pipe.execute()
        return True

    async def request_cancel(self, session_id: UUID, run_id: str) -> None:
        """写入可被任意 worker 消费的取消请求；TTL 防止进程崩溃后留下脏键。"""
        if self._redis is None:
            raise NotFoundError(f"Run {run_id} is not active")
        owner = await self._redis.get(self._key(f"owner:{run_id}"))
        if _as_text(owner) != str(session_id):
            raise NotFoundError(f"Run {run_id} is not active")
        await self._redis.set(
            self._key(f"cancel:{run_id}"),
            str(session_id),
            ex=CANCEL_REQUEST_TTL_SECONDS,
        )

    async def cancellation_requested(self, session_id: UUID, run_id: str) -> bool:
        if self._redis is None:
            return False
        requested = await self._redis.get(self._key(f"cancel:{run_id}"))
        return _as_text(requested) == str(session_id)

    async def aclose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    def _key(self, suffix: str) -> str:
        return f"{self._prefix}:{suffix}"


def _as_text(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


def _as_uuid(value: bytes | str) -> UUID:
    return UUID(_as_text(value) or "")
