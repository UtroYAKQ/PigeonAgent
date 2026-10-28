from __future__ import annotations

import asyncio
import itertools
from collections import deque
from typing import TYPE_CHECKING

from ag_ui.core import BaseEvent

from app.render.events import RenderEvent

if TYPE_CHECKING:
    from app.render.consumer import RenderConsumer

MAX_BACKLOG = 10_000


class RenderCursorInvalid(ValueError):
    """消费者游标越界。"""


class RenderQueue:
    """单轮运行的广播事件队列：事件保留到运行结束，供多个消费者各自回放。

    backlog 超过 max_backlog 时丢弃最旧事件；早于最早可用事件的回放
    会退化为从现存最早的事件开始。
    """

    def __init__(self, run_id: str, *, max_backlog: int = MAX_BACKLOG) -> None:
        self.run_id = run_id
        self._events: deque[RenderEvent] = deque(maxlen=max_backlog or None)
        self._closed = False
        self._seq = 0
        self._condition = asyncio.Condition()

    async def publish(self, event: BaseEvent) -> None:
        async with self._condition:
            if self._closed:
                raise RuntimeError(f"Render queue for run {self.run_id} is closed")
            self._seq += 1
            self._events.append(RenderEvent(seq=self._seq, event=event))
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    def subscribe(self, after: int = 0) -> RenderConsumer:
        if not 0 <= after <= self._seq:
            raise RenderCursorInvalid(f"Event cursor {after} is out of range")
        from app.render.consumer import RenderConsumer

        return RenderConsumer(self, after)

    async def read_after(self, cursor: int) -> tuple[list[RenderEvent], bool]:
        async with self._condition:
            while self._seq <= cursor and not self._closed:
                await self._condition.wait()
            first = self._seq - len(self._events) + 1
            start = max(cursor + 1 - first, 0)
            return list(itertools.islice(self._events, start, None)), self._closed
