"""Redis 后端的渲染队列测试：与进程内实现跑同一套语义，外加跨进程场景。"""

import asyncio
from uuid import uuid4

import pytest
from ag_ui.core import RunFinishedEvent, RunStartedEvent, TextMessageContentEvent
from fakeredis import FakeAsyncRedis

from app.core.exceptions import ConflictError
from app.render import RenderConsumer, RenderCursorInvalid, RenderEvent, RenderHub

SESSION_ID = uuid4()


def build_hub(client: FakeAsyncRedis, *, prefix: str | None = None) -> RenderHub:
    """prefix 传同一个值 = 模拟两个 worker 进程共享同一份 Redis 状态。"""
    return RenderHub(
        redis_client=client, key_prefix=prefix or f"test-{uuid4().hex[:8]}", retain_seconds=600
    )


def text(delta: str = "x") -> TextMessageContentEvent:
    return TextMessageContentEvent(message_id="m", delta=delta)


async def drain(consumer: RenderConsumer) -> list[RenderEvent]:
    return [item async for item in consumer]


async def test_broadcasts_to_independent_consumers() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-1")
    first = await hub.subscribe("run-1")
    second = await hub.subscribe("run-1")
    assert first is not None and second is not None

    await producer.publish(RunStartedEvent(thread_id=str(SESSION_ID), run_id="run-1"))
    await producer.publish(text("你好"))
    await producer.close()

    first_items = await drain(first)
    second_items = await drain(second)
    assert [item.seq for item in first_items] == [1, 2]
    assert [item.seq for item in second_items] == [1, 2]
    assert first_items[1].event == second_items[1].event
    assert await hub.subscribe("run-1") is None


async def test_consumer_waits_for_new_events() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-2")
    await producer.publish(RunStartedEvent(thread_id=str(SESSION_ID), run_id="run-2"))

    consumer = await hub.subscribe("run-2")
    assert consumer is not None
    task = asyncio.create_task(drain(consumer))
    await asyncio.sleep(0.1)
    await producer.publish(text("后到的事件"))
    await producer.close()

    items = await task
    assert [item.seq for item in items] == [1, 2]
    assert "后到的事件" in items[1].event.model_dump_json()


async def test_subscribe_after_cursor_resumes_mid_stream() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-3")
    for index in range(3):
        await producer.publish(text(str(index)))

    consumer = await hub.subscribe("run-3", after=1)
    assert consumer is not None
    await producer.close()

    items = await drain(consumer)
    assert [item.seq for item in items] == [2, 3]


async def test_invalid_cursor_is_rejected() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-4")
    await producer.publish(text())

    with pytest.raises(RenderCursorInvalid):
        await hub.subscribe("run-4", after=2)
    assert await hub.subscribe("unknown-run") is None
    await producer.close()


async def test_one_active_run_per_session() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-6")

    with pytest.raises(ConflictError):
        await hub.create(SESSION_ID, "run-7")
    other = await hub.create(uuid4(), "run-7")
    await producer.close()
    await other.close()

    reused = await hub.create(SESSION_ID, "run-8")
    await reused.close()


async def test_run_finished_frees_the_session_slot() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-a")
    await producer.close()

    next_producer = await hub.create(SESSION_ID, "run-b")
    await next_producer.close()


async def test_two_hubs_share_one_redis_like_two_workers() -> None:
    """跨进程等价场景：A 进程建流发事件，B 进程按游标接入回放。"""
    client = FakeAsyncRedis()
    prefix = f"test-{uuid4().hex[:8]}"
    hub_a = build_hub(client, prefix=prefix)
    hub_b = build_hub(client, prefix=prefix)
    producer = await hub_a.create(SESSION_ID, "shared-run")
    await producer.publish(RunStartedEvent(thread_id=str(SESSION_ID), run_id="shared-run"))
    await producer.publish(text("one"))

    consumer = await hub_b.subscribe("shared-run", session_id=SESSION_ID)
    assert consumer is not None
    await producer.publish(text("two"))
    await producer.close()

    items = await drain(consumer)
    assert [item.seq for item in items] == [1, 2, 3]

    # close 之后 B 侧的互斥标记也要解掉
    next_producer = await hub_b.create(SESSION_ID, "next-run")
    await next_producer.close()


async def test_late_subscriber_gets_none_but_attached_consumer_drains() -> None:
    """close 后迟到的订阅者拿不到流（SSE 端点回 410），先接上的消费者照常读完。"""
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-keep")
    await producer.publish(text("kept"))
    consumer = await hub.subscribe("run-keep")
    assert consumer is not None
    await producer.publish(text("after-close"))
    await producer.close()

    assert await hub.subscribe("run-keep") is None
    items = await drain(consumer)
    assert [item.seq for item in items] == [1, 2]


async def test_publish_after_close_is_rejected() -> None:
    hub = build_hub(FakeAsyncRedis())
    producer = await hub.create(SESSION_ID, "run-closed")
    await producer.close()

    with pytest.raises(RuntimeError):
        await producer.publish(RunFinishedEvent(thread_id=str(SESSION_ID), run_id="run-closed"))
