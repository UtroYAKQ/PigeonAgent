from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.render.events import RenderEvent

if TYPE_CHECKING:
    from app.render.queue import RenderStream


class RenderConsumer:
    """一条独立的读取游标；多个消费者互不影响。退出时通知队列回收落盘文件。"""

    def __init__(self, queue: RenderStream, after: int = 0) -> None:
        self._queue = queue
        self._cursor = after
        self._closed = False

    async def read(self) -> tuple[list[RenderEvent], bool]:
        """读一批 cursor 之后的事件；游标推进到最后一条。"""
        events, closed = await self._queue.read_after(self._cursor)
        if events:
            self._cursor = events[-1].seq
        return events, closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.release()

    async def __aiter__(self) -> AsyncIterator[RenderEvent]:
        try:
            while True:
                events, closed = await self.read()
                for item in events:
                    yield item
                if closed:
                    return
        finally:
            self.close()
