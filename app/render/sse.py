"""SSE 编码：运行事件流的心跳与帧格式只在这里维护一份。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.render.consumer import RenderConsumer

# 工具长时间运行期间保持连接不被反代/客户端掐断
HEARTBEAT_INTERVAL_SECONDS = 15.0


async def encode_consumer(consumer: RenderConsumer) -> AsyncIterator[str]:
    try:
        while True:
            try:
                async with asyncio.timeout(HEARTBEAT_INTERVAL_SECONDS):
                    events, closed = await consumer.read()
            except TimeoutError:
                yield ": ping\n\n"
                continue
            for item in events:
                yield f"id: {item.seq}\ndata: {item.event.model_dump_json(by_alias=True)}\n\n"
            if closed:
                return
    finally:
        # 消费者退出后队列才知道落盘文件可以回收了
        consumer.close()
