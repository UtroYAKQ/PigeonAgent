from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from ag_ui.core import BaseEvent

if TYPE_CHECKING:
    from app.render.hub import RenderHub
    from app.render.queue import RenderQueue


class RenderProducer:
    """绑定一次运行和它的队列；close 时从 hub 摘除队列。"""

    def __init__(self, hub: RenderHub, session_id: UUID, queue: RenderQueue) -> None:
        self._hub = hub
        self._session_id = session_id
        self._queue = queue
        self._closed = False

    async def publish(self, event: BaseEvent) -> None:
        await self._queue.publish(event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._hub.finish(self._session_id, self._queue.run_id)
