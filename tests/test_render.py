import asyncio
import tempfile
from uuid import uuid4

import pytest
from ag_ui.core import BaseEvent, RunFinishedEvent, RunStartedEvent, TextMessageContentEvent

from app.core.exceptions import ConflictError
from app.render import RenderConsumer, RenderCursorInvalid, RenderEvent, RenderHub
from app.render.queue import memory as render_queue

SESSION_ID = uuid4()


def started(run_id: str = "run-1") -> BaseEvent:
    return RunStartedEvent(thread_id=str(SESSION_ID), run_id=run_id)


def text(delta: str = "x") -> BaseEvent:
    return TextMessageContentEvent(message_id="m", delta=delta)


def finished(run_id: str = "run-1") -> BaseEvent:
    return RunFinishedEvent(thread_id=str(SESSION_ID), run_id=run_id)


async def drain(consumer: RenderConsumer) -> list[RenderEvent]:
    return [item async for item in consumer]


async def test_broadcasts_to_independent_consumers() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-1")
    first = await hub.subscribe("run-1")
    second = await hub.subscribe("run-1")
    assert first is not None and second is not None

    await producer.publish(started())
    await producer.publish(text("你好"))
    await producer.close()

    first_items = await drain(first)
    second_items = await drain(second)
    assert [item.seq for item in first_items] == [1, 2]
    assert [item.seq for item in second_items] == [1, 2]
    assert first_items[1].event == second_items[1].event
    assert await hub.subscribe("run-1") is None


async def test_consumer_waits_for_new_events_and_replays_from_start() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-2")
    await producer.publish(started("run-2"))

    consumer = await hub.subscribe("run-2")
    assert consumer is not None
    task = asyncio.create_task(drain(consumer))
    await asyncio.sleep(0)
    await producer.publish(text("后到的事件"))
    await producer.close()

    items = await task
    assert [item.seq for item in items] == [1, 2]
    assert "后到的事件" in items[1].event.model_dump_json()


async def test_subscribe_after_cursor_resumes_mid_stream() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-3")
    for index in range(3):
        await producer.publish(text(str(index)))

    consumer = await hub.subscribe("run-3", after=1)
    assert consumer is not None
    await producer.close()

    items = await drain(consumer)
    assert [item.seq for item in items] == [2, 3]


async def test_invalid_cursor_is_rejected() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-4")
    await producer.publish(text())

    with pytest.raises(RenderCursorInvalid):
        await hub.subscribe("run-4", after=2)
    assert await hub.subscribe("unknown-run") is None
    await producer.close()


async def test_finish_detaches_queue_but_attached_consumer_drains() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-5")
    consumer = await hub.subscribe("run-5")
    assert consumer is not None

    await producer.publish(started("run-5"))
    await producer.publish(finished("run-5"))
    await producer.close()

    assert await hub.subscribe("run-5") is None
    items = await drain(consumer)
    assert [item.seq for item in items] == [1, 2]


async def test_one_active_run_per_session() -> None:
    hub = RenderHub()
    producer = await hub.create(SESSION_ID, "run-6")
    other_session = uuid4()

    with pytest.raises(ConflictError):
        await hub.create(SESSION_ID, "run-7")
    other = await hub.create(other_session, "run-7")
    await producer.close()
    await other.close()

    reused = await hub.create(SESSION_ID, "run-8")
    await reused.close()


def spool_files(tmp_path) -> list:
    return list(tmp_path.glob("*.jsonl"))


async def test_backlog_overflows_to_jsonl_and_replays(tmp_path, monkeypatch) -> None:
    """内存窗口装满后旧事件落盘，回放不丢；消费者全部退出后文件删除。"""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    hub = RenderHub(max_backlog=2)
    run_id = f"spill-{uuid4().hex}"
    producer = await hub.create(SESSION_ID, run_id)
    for index in range(5):
        await producer.publish(text(str(index)))

    first = await hub.subscribe(run_id, after=0)
    second = await hub.subscribe(run_id, after=4)
    assert first is not None and second is not None
    await producer.close()

    files = spool_files(tmp_path)
    assert files, "超出上限的事件要落到临时文件"

    first_items = await drain(first)
    assert [item.seq for item in first_items] == [1, 2, 3, 4, 5]
    assert [item.event.delta for item in first_items] == ["0", "1", "2", "3", "4"]
    assert files[0].exists(), "还有消费者时文件不能删"

    second_items = await drain(second)
    assert [item.seq for item in second_items] == [5]
    assert not files[0].exists(), "消费者全部退出后临时文件要删掉"


async def test_cursor_inside_spilled_range_resumes_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    hub = RenderHub(max_backlog=2)
    run_id = f"spill-{uuid4().hex}"
    producer = await hub.create(SESSION_ID, run_id)
    for index in range(6):
        await producer.publish(text(str(index)))

    consumer = await hub.subscribe(run_id, after=3)
    assert consumer is not None
    await producer.close()

    items = await drain(consumer)
    assert [item.seq for item in items] == [4, 5, 6]
    assert spool_files(tmp_path) == []


async def test_spilled_events_replay_in_chunks(tmp_path, monkeypatch) -> None:
    """落盘文件按批回放，队列已关闭也要把剩下的批次读完再结束。"""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(render_queue, "SPOOL_BATCH", 2)
    hub = RenderHub(max_backlog=1)
    run_id = f"spill-{uuid4().hex}"
    producer = await hub.create(SESSION_ID, run_id)
    for index in range(6):
        await producer.publish(text(str(index)))

    consumer = await hub.subscribe(run_id, after=0)
    assert consumer is not None
    await producer.close()

    items = await drain(consumer)
    assert [item.seq for item in items] == [1, 2, 3, 4, 5, 6]
