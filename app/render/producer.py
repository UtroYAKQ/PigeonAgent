from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from ag_ui.core import BaseEvent

if TYPE_CHECKING:
    from app.render.hub import RenderHub
    from app.render.queue import RenderStream

logger = logging.getLogger(__name__)


class RenderProducer:
    """绑定一次运行和它的队列；close 时先封流再从注册表摘除。"""

    def __init__(self, hub: RenderHub, session_id: UUID, queue: RenderStream) -> None:
        self._hub = hub
        self._session_id = session_id
        self._queue = queue
        self._closed = False

    async def publish(self, event: BaseEvent) -> None:
        await self._queue.publish(event)

    async def touch(self) -> None:
        """run 租约心跳时顺手续期活跃标记。"""
        await self._hub.touch(self._session_id, self._queue.run_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.close()
        await self._hub.finish(self._session_id, self._queue.run_id)
