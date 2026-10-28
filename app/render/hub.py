from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError
from app.render.producer import RenderProducer
from app.render.queue import RenderQueue

if TYPE_CHECKING:
    from app.render.consumer import RenderConsumer


class RenderHub:
    """单进程内的运行队列注册表：每个 session 同时只允许一个活跃运行。"""

    def __init__(self) -> None:
        self._queues: dict[str, RenderQueue] = {}
        self._active: dict[UUID, str] = {}
        self._owners: dict[str, UUID] = {}

    def create(self, session_id: UUID, run_id: str) -> RenderProducer:
        if run_id in self._queues:
            raise ConflictError(f"Run {run_id} is already streaming")
        if session_id in self._active:
            raise ConflictError(f"Session {session_id} already has an active run")
        queue = RenderQueue(run_id)
        self._queues[run_id] = queue
        self._owners[run_id] = session_id
        self._active[session_id] = run_id
        return RenderProducer(self, session_id, queue)

    def subscribe(
        self, run_id: str, after: int = 0, *, session_id: UUID | None = None
    ) -> RenderConsumer | None:
        owner = self._owners.get(run_id)
        if owner is not None and session_id is not None and owner != session_id:
            raise NotFoundError(f"Run {run_id} does not belong to session {session_id}")
        queue = self._queues.get(run_id)
        return None if queue is None else queue.subscribe(after)

    async def finish(self, session_id: UUID, run_id: str) -> None:
        queue = self._queues.pop(run_id, None)
        self._owners.pop(run_id, None)
        if self._active.get(session_id) == run_id:
            del self._active[session_id]
        if queue is not None:
            await queue.close()
