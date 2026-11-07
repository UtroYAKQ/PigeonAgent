from __future__ import annotations

import asyncio
import bisect
import contextlib
import itertools
import json
import logging
import os
import re
import tempfile
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO

from ag_ui.core import BaseEvent, Event
from pydantic import TypeAdapter

from app.render.events import RenderEvent

if TYPE_CHECKING:
    from app.render.consumer import RenderConsumer

logger = logging.getLogger(__name__)

MAX_BACKLOG = 10_000
# 落盘文件每 N 条记一个偏移；回放时最多顺扫 N 行，不用从头扫到尾
SPOOL_INDEX_STRIDE = 256
# 单次从落盘文件回放的上限，避免把大文件一次性读成巨大的 list
SPOOL_BATCH = 1_000

_EVENT_ADAPTER = TypeAdapter(Event)


class RenderCursorInvalid(ValueError):
    """消费者游标越界。"""


class RenderStream(Protocol):
    """渲染队列的对外契约：进程内与 Redis 两种实现都长这样。"""

    run_id: str

    async def publish(self, event: BaseEvent) -> None: ...

    async def close(self) -> None: ...

    async def last_seq(self) -> int: ...

    def consumer(self, after: int) -> RenderConsumer: ...

    async def read_after(self, cursor: int) -> tuple[list[RenderEvent], bool]: ...

    def release(self) -> None: ...


class RenderQueue:
    """单轮运行的广播事件队列：事件保留到运行结束，供多个消费者各自回放。

    backlog 超过 max_backlog 时，最旧的事件落到临时 jsonl 文件而不是丢弃：
    内存只留最近的一窗，回放旧游标时从文件补齐。队列结束且消费者全部
    退出后临时文件即删。max_backlog=0 表示不限。
    """

    def __init__(self, run_id: str, *, max_backlog: int = MAX_BACKLOG) -> None:
        self.run_id = run_id
        # 配置里 0 的语义是"不限"，写清楚，别靠 or 的假值技巧
        self._max_backlog = None if max_backlog == 0 else max_backlog
        self._events: deque[RenderEvent] = deque()
        self._closed = False
        self._seq = 0
        self._condition = asyncio.Condition()
        self._spool: TextIO | None = None
        self._spool_path: Path | None = None
        # (seq, file offset)：每隔 SPOOL_INDEX_STRIDE 条记一次，用于 seek
        self._spool_index: list[tuple[int, int]] = []
        # 已成功落盘的事件数；落盘 seq 从 1 起连续，内存窗口起点就是它 + 1
        self._spooled = 0
        self._spool_broken = False
        self._consumers = 0

    async def publish(self, event: BaseEvent) -> None:
        async with self._condition:
            if self._closed:
                raise RuntimeError(f"Render queue for run {self.run_id} is closed")
            self._seq += 1
            self._events.append(RenderEvent(seq=self._seq, event=event))
            while self._max_backlog is not None and len(self._events) > self._max_backlog:
                self._spill(self._events.popleft())
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._discard_spool_if_unused()

    async def last_seq(self) -> int:
        return self._seq

    def consumer(self, after: int) -> RenderConsumer:
        from app.render.consumer import RenderConsumer

        self._consumers += 1
        return RenderConsumer(self, after)

    def release(self) -> None:
        """消费者退出；最后一个消费者走了、队列也结束了，临时文件就可以删了。"""
        self._consumers = max(0, self._consumers - 1)
        self._discard_spool_if_unused()

    async def read_after(self, cursor: int) -> tuple[list[RenderEvent], bool]:
        async with self._condition:
            while self._seq <= cursor and not self._closed:
                await self._condition.wait()
            events = self._read_spool(cursor)
            if events:
                # 分片回放时后面可能还有内存窗口里的事件，没读完不能算 closed
                return events, self._closed and events[-1].seq >= self._seq
            first = self._seq - len(self._events) + 1
            start = max(cursor + 1 - first, 0)
            return list(itertools.islice(self._events, start, None)), self._closed

    # ------------------------------------------------------------ 落盘

    def _spill(self, item: RenderEvent) -> None:
        """把最旧的事件追加到临时 jsonl；写失败就退化成丢弃，内存上限优先。"""
        if self._spool_broken:
            return
        try:
            if self._spool is None:
                prefix = re.sub(r"[^0-9A-Za-z_.-]", "_", self.run_id)
                fd, name = tempfile.mkstemp(prefix=f"pigeon-render-{prefix}-", suffix=".jsonl")
                self._spool = os.fdopen(fd, "w", encoding="utf-8")
                self._spool_path = Path(name)
            spool = self._spool
            if (item.seq - 1) % SPOOL_INDEX_STRIDE == 0:
                self._spool_index.append((item.seq, spool.tell()))
            payload = {
                "seq": item.seq,
                "event": item.event.model_dump(mode="json", by_alias=True),
            }
            spool.write(json.dumps(payload, ensure_ascii=False) + "\n")
            # 不逐条 flush：溢出时每条事件一次磁盘同步，全砸在广播临界区里。
            # 读的一侧（_read_spool）会先把缓冲刷出去，可见性一样。
            self._spooled += 1
        except OSError:
            self._spool_broken = True
            logger.warning(
                "Render spool for run %s is unwritable; dropping oldest events instead",
                self.run_id,
                exc_info=True,
            )
            self._discard_spool()

    def _read_spool(self, cursor: int) -> list[RenderEvent]:
        if self._spool_path is None or cursor >= self._spooled:
            return []
        events: list[RenderEvent] = []
        try:
            if self._spool is not None:
                # 写缓冲里的内容对另一个文件句柄不可见，读之前先刷出去
                self._spool.flush()
            with self._spool_path.open("r", encoding="utf-8") as handle:
                handle.seek(self._spool_offset(cursor + 1))
                for line in handle:
                    try:
                        payload = json.loads(line)
                        seq = int(payload["seq"])
                        if seq <= cursor:
                            continue
                        event = _EVENT_ADAPTER.validate_python(payload["event"])
                    except (ValueError, KeyError, TypeError):
                        continue  # 残行/坏行跳过，回放不能因为一行坏掉整体失败
                    events.append(RenderEvent(seq=seq, event=event))
                    if len(events) >= SPOOL_BATCH:
                        break
        except OSError:
            logger.warning(
                "Render spool for run %s is unreadable; replay starts from memory window",
                self.run_id,
                exc_info=True,
            )
            return []
        return events

    def _spool_offset(self, seq: int) -> int:
        index = bisect.bisect_right(self._spool_index, (seq, float("inf"))) - 1
        return self._spool_index[index][1] if index >= 0 else 0

    def _discard_spool_if_unused(self) -> None:
        if self._closed and self._consumers == 0:
            self._discard_spool()

    def _discard_spool(self) -> None:
        spool, path = self._spool, self._spool_path
        self._spool = None
        self._spool_path = None
        self._spool_index.clear()
        if spool is not None:
            with contextlib.suppress(OSError):
                spool.close()
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
