from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.render.events import RenderEvent

if TYPE_CHECKING:
    from app.render.queue import RenderQueue


class RenderConsumer:
    """一条独立的读取游标；多个消费者互不影响。"""

    def __init__(self, queue: RenderQueue, after: int = 0) -> None:
        self._queue = queue
        self._cursor = after

    async def read(self) -> tuple[list[RenderEvent], bool]:
        """读一批 cursor 之后的事件；游标推进到最后一条。"""
        events, closed = await self._queue.read_after(self._cursor)
        if events:
            self._cursor = events[-1].seq
        return events, closed

    async def __aiter__(self) -> AsyncIterator[RenderEvent]:
        while True:
            events, closed = await self.read()
            for item in events:
                yield item
            if closed:
                return
