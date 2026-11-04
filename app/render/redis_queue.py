"""Redis Streams 实现的渲染队列：跨进程共享，多消费者各自游标。

事件以显式 id ``0-{seq}`` 写进 stream：seq 由 INCR 严格递增，与进程内
实现的游标语义、SSE 的 ``id:`` 字段完全一致。close 写一条 ``closed``
墓碑进流里，末尾的消费者也能立刻看到结束标记。

读取不用 XREAD BLOCK：轮询 XRANGE 免掉取消长阻塞命令时的连接复位，
轮询间隔随空闲程度退避，流式高峰期几乎即时。run 结束后流数据保留
``retain`` 秒，迟到标签页仍能回放，之后由 Redis 过期自动回收。
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from ag_ui.core import BaseEvent
from pydantic import TypeAdapter
from redis.asyncio import Redis

from app.render.consumer import RenderConsumer
from app.render.events import RenderEvent

logger = logging.getLogger(__name__)

_EVENT_ADAPTER = TypeAdapter(BaseEvent)

_READ_BATCH = 500
_ACTIVE_POLL_SECONDS = 0.05
_IDLE_POLL_SECONDS = 1.0
_IDLE_AFTER_EMPTY = 3
# 活跃期间每次发布都续期：等价于「run 进行中永不过期」
_ACTIVE_STREAM_TTL_SECONDS = 86_400


class RedisRenderQueue:
    def __init__(
        self,
        client: Redis,
        run_id: str,
        *,
        key_prefix: str = "pigeon",
        retain_seconds: int = 600,
    ) -> None:
        self.run_id = run_id
        self._client = client
        self._stream = f"{key_prefix}:render:stream:{run_id}"
        self._seq_key = f"{key_prefix}:render:seq:{run_id}"
        self._closed_key = f"{key_prefix}:render:closed:{run_id}"
        self._retain = retain_seconds
        self._closed = False

    async def publish(self, event: BaseEvent) -> None:
        if self._closed:
            raise RuntimeError(f"Render queue for run {self.run_id} is closed")
        seq = await self._client.incr(self._seq_key)
        payload = event.model_dump_json(by_alias=True)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xadd(self._stream, {"event": payload}, id=f"0-{seq}")
            pipe.expire(self._stream, _ACTIVE_STREAM_TTL_SECONDS)
            pipe.expire(self._seq_key, _ACTIVE_STREAM_TTL_SECONDS)
            await pipe.execute()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # 墓碑也占一个 seq：排在所有事件之后，消费者读到它就知道流结束了
        seq = await self._client.incr(self._seq_key)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xadd(self._stream, {"closed": "1"}, id=f"0-{seq}")
            pipe.expire(self._stream, self._retain)
            pipe.expire(self._seq_key, self._retain)
            pipe.set(self._closed_key, "1", ex=self._retain)
            await pipe.execute()

    async def last_seq(self) -> int:
        value = await self._client.get(self._seq_key)
        return int(value or 0)

    def consumer(self, after: int) -> RenderConsumer:
        # 游标合法性由 hub 在异步侧对 last_seq() 校验后调用
        return RenderConsumer(self, after)

    async def read_after(self, cursor: int) -> tuple[list[RenderEvent], bool]:
        empty_rounds = 0
        while True:
            raw = await self._client.xrange(
                self._stream, min=f"(0-{cursor}", max="+", count=_READ_BATCH
            )
            entries = cast("list[tuple[bytes, dict[bytes | str, bytes | str]]]", raw or [])
            events: list[RenderEvent] = []
            closed = False
            for entry_id, fields in entries:
                if _field(fields, "closed") is not None:
                    closed = True
                    break
                seq = _seq_of(entry_id)
                payload = _field(fields, "event")
                if seq is None or payload is None:
                    continue
                try:
                    event = _EVENT_ADAPTER.validate_json(payload)
                except ValueError:
                    # 和进程内实现保持一致：坏的一条跳过，别把整条回放链路炸掉
                    logger.warning("Skipping unreadable event seq=%s for run %s", seq, self.run_id)
                    continue
                events.append(RenderEvent(seq=seq, event=event))
            if events or closed:
                return events, closed
            # 没有新事件：墓碑可能早于当前游标（已消费过），看关闭标记
            if await self._client.get(self._closed_key):
                return [], True
            empty_rounds += 1
            delay = (
                _IDLE_POLL_SECONDS if empty_rounds >= _IDLE_AFTER_EMPTY else _ACTIVE_POLL_SECONDS
            )
            await asyncio.sleep(delay)

    def release(self) -> None:
        """消费者退出钩子；进程内实现用它回收落盘文件，这里由 Redis 过期兜底。"""


def _seq_of(entry_id: bytes | str) -> int | None:
    text = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
    try:
        return int(text.split("-", 1)[1])
    except (IndexError, ValueError):
        return None


def _field(fields: dict[bytes | str, bytes | str], name: str) -> str | None:
    value = fields.get(name) or fields.get(name.encode())
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value
