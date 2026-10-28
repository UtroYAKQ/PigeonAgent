import asyncio
from collections.abc import AsyncIterator, Coroutine
from typing import Any
from uuid import UUID, uuid4

from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunStartedEvent, TextMessageContentEvent
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.llm_model import LlmModel
from app.models.session_run import SessionRun
from app.render import RenderConsumer, RenderEvent, RenderHub
from app.schemas.run_item import ErrorItem, TextItem
from app.schemas.session import SessionCreate
from app.services import chat_session as session_service
from app.services import run as run_service
from app.services import session_run as run_service_data
from app.services.model_factory import ModelFactory, ResolvedModel
from app.services.run import RunRegistry
from tests.conftest import TEST_USER_ID


async def drain(consumer: RenderConsumer) -> list[RenderEvent]:
    return [item async for item in consumer]


def get_hub() -> RenderHub:
    hub = app.state.render_hub
    assert isinstance(hub, RenderHub)
    return hub


async def make_stream_session(db_session: AsyncSession, title: str = "sse") -> UUID:
    """事件端点现在要求会话存在且归属调用者，SSE 单测先落一行头。"""
    created = await session_service.create_session(
        db_session, SessionCreate(title=title), owner_id=TEST_USER_ID
    )
    return created.id


async def test_sse_stream_frames_events(client: AsyncClient, db_session: AsyncSession) -> None:
    hub = get_hub()
    session_id = await make_stream_session(db_session)
    producer = hub.create(session_id, "run-sse")
    await producer.publish(RunStartedEvent(thread_id="t", run_id="run-sse"))

    request = asyncio.create_task(client.get(f"/api/v1/sessions/{session_id}/runs/run-sse/events"))
    await asyncio.sleep(0.05)
    await producer.publish(TextMessageContentEvent(message_id="m", delta="hello"))
    await producer.publish(RunFinishedEvent(thread_id="t", run_id="run-sse"))
    await producer.close()
    response = await request

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "id: 1" in body
    assert '"delta":"hello"' in body
    assert "id: 3" in body


async def test_sse_resumes_from_last_event_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hub = get_hub()
    session_id = await make_stream_session(db_session)
    producer = hub.create(session_id, "run-resume")
    for index in range(3):
        await producer.publish(TextMessageContentEvent(message_id="m", delta=str(index)))

    request = asyncio.create_task(
        client.get(
            f"/api/v1/sessions/{session_id}/runs/run-resume/events",
            headers={"Last-Event-ID": "1"},
        )
    )
    await asyncio.sleep(0.05)
    await producer.close()
    response = await request

    assert response.status_code == 200
    body = response.text
    assert "id: 1" not in body
    assert "id: 2" in body
    assert "id: 3" in body


async def test_stream_unknown_run_is_gone(client: AsyncClient, db_session: AsyncSession) -> None:
    session_id = await make_stream_session(db_session)
    response = await client.get(f"/api/v1/sessions/{session_id}/runs/missing/events")

    assert response.status_code == 410


async def test_stream_rejects_invalid_cursor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hub = get_hub()
    session_id = await make_stream_session(db_session)
    producer = hub.create(session_id, "run-cursor")
    await producer.publish(TextMessageContentEvent(message_id="m", delta="x"))

    response = await client.get(f"/api/v1/sessions/{session_id}/runs/run-cursor/events?after=5")
    assert response.status_code == 422

    bad_header = await client.get(
        f"/api/v1/sessions/{session_id}/runs/run-cursor/events",
        headers={"Last-Event-ID": "abc"},
    )
    assert bad_header.status_code == 422
    await producer.close()


async def test_stream_rejects_wrong_session(client: AsyncClient) -> None:
    hub = get_hub()
    producer = hub.create(uuid4(), "run-owner")
    try:
        response = await client.get(f"/api/v1/sessions/{uuid4()}/runs/run-owner/events")
        assert response.status_code == 404
    finally:
        await producer.close()


async def test_two_sse_consumers_receive_same_stream(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    hub = get_hub()
    session_id = await make_stream_session(db_session)
    producer = hub.create(session_id, "run-multi")
    url = f"/api/v1/sessions/{session_id}/runs/run-multi/events"

    first = asyncio.create_task(client.get(url))
    second = asyncio.create_task(client.get(url))
    await asyncio.sleep(0.05)
    await producer.publish(TextMessageContentEvent(message_id="m", delta="hello"))
    await producer.publish(RunFinishedEvent(thread_id="t", run_id="run-multi"))
    await producer.close()

    first_response, second_response = await asyncio.gather(first, second)
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.text == second_response.text
    assert "id: 1" in first_response.text
    assert "id: 2" in first_response.text


async def test_start_run_marks_session_active(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    model = LlmModel(
        name="render-model",
        provider="openai",
        model_name="gpt-4o-mini",
        owner_id=TEST_USER_ID,
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    created = await session_service.create_session(
        db_session,
        SessionCreate(title="render", model_id=model.id),
        owner_id=TEST_USER_ID,
    )

    resolved = ResolvedModel(
        name="render-model",
        # BaseAgent 自带工具，而 TestModel 默认把每个工具都调一遍；这里只验渲染链路
        model=TestModel(custom_output_text="ok", call_tools=[]),
        settings={},
        context_window=None,
        supports_tools=False,
    )

    def fake_create(_self: object, _record: LlmModel) -> ResolvedModel:
        return resolved

    scheduled: list[Coroutine[Any, Any, None]] = []

    def fake_schedule(self: object, coro: Coroutine[Any, Any, None]) -> None:
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(ModelFactory, "create", fake_create)
    monkeypatch.setattr(RunRegistry, "schedule", fake_schedule)

    response = await client.post(f"/api/v1/sessions/{created.id}/runs", json={"input": "你好"})
    assert response.status_code == 202
    body = response.json()
    run_id: str = body["run_id"]
    assert scheduled

    session_response = await client.get(f"/api/v1/sessions/{created.id}")
    assert session_response.json()["active_run_id"] == run_id

    runs_response = await client.get(f"/api/v1/sessions/{created.id}/runs")
    items = runs_response.json()["items"]
    assert len(items) == 1
    assert [item["type"] for item in items[0]["content"]] == ["text"]
    assert items[0]["content"][0]["role"] == "user"

    conflict = await client.post(f"/api/v1/sessions/{created.id}/runs", json={"input": "再来一轮"})
    assert conflict.status_code == 409

    await get_hub().finish(created.id, run_id)


async def test_end_to_end_run_streams_and_finalizes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    model = LlmModel(
        name="stream-model",
        provider="openai",
        model_name="gpt-4o-mini",
        owner_id=TEST_USER_ID,
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    created = await session_service.create_session(
        db_session,
        SessionCreate(title="stream", model_id=model.id),
        owner_id=TEST_USER_ID,
    )

    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        started.set()
        await release.wait()
        yield "你"
        yield "好"

    resolved = ResolvedModel(
        name="stream-model",
        model=FunctionModel(stream_function=gated_stream),
        settings={},
        context_window=None,
        supports_tools=False,
    )

    def fake_create(_self: object, _record: LlmModel) -> ResolvedModel:
        return resolved

    monkeypatch.setattr(ModelFactory, "create", fake_create)

    response = await client.post(f"/api/v1/sessions/{created.id}/runs", json={"input": "打个招呼"})
    assert response.status_code == 202
    body = response.json()
    run_id: str = body["run_id"]
    await asyncio.wait_for(started.wait(), timeout=1)

    request = asyncio.create_task(client.get(f"/api/v1/sessions/{created.id}/runs/{run_id}/events"))
    await asyncio.sleep(0.05)
    release.set()
    stream = await request

    assert stream.status_code == 200
    assert "RUN_STARTED" in stream.text
    assert "RUN_FINISHED" in stream.text
    assert run_id in stream.text
    assert "threadId" in stream.text
    assert "thread_id" not in stream.text

    session_response = await client.get(f"/api/v1/sessions/{created.id}")
    assert session_response.json()["active_run_id"] is None
    runs_response = await client.get(f"/api/v1/sessions/{created.id}/runs")
    content = runs_response.json()["items"][-1]["content"]
    assert [item["role"] for item in content if item["type"] == "text"] == ["user", "assistant"]
    assert get_hub().subscribe(run_id) is None


async def test_cancel_run_clears_active_run(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    model = LlmModel(
        name="cancel-model",
        provider="openai",
        model_name="gpt-4o-mini",
        owner_id=TEST_USER_ID,
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    created = await session_service.create_session(
        db_session,
        SessionCreate(title="cancel", model_id=model.id),
        owner_id=TEST_USER_ID,
    )

    started = asyncio.Event()

    async def gated_stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        started.set()
        await asyncio.sleep(30)
        yield "never"

    resolved = ResolvedModel(
        name="cancel-model",
        model=FunctionModel(stream_function=gated_stream),
        settings={},
        context_window=None,
        supports_tools=False,
    )

    def fake_create(_self: object, _record: LlmModel) -> ResolvedModel:
        return resolved

    monkeypatch.setattr(ModelFactory, "create", fake_create)

    response = await client.post(f"/api/v1/sessions/{created.id}/runs", json={"input": "写很久"})
    assert response.status_code == 202
    body = response.json()
    run_id: str = body["run_id"]
    await asyncio.wait_for(started.wait(), timeout=1)

    stream = asyncio.create_task(client.get(f"/api/v1/sessions/{created.id}/runs/{run_id}/events"))
    await asyncio.sleep(0.05)
    cancel = await client.post(f"/api/v1/sessions/{created.id}/runs/{run_id}/cancel")
    assert cancel.status_code == 202
    stream_response = await asyncio.wait_for(stream, timeout=5)
    assert stream_response.status_code == 200

    session_response = await client.get(f"/api/v1/sessions/{created.id}")
    assert session_response.json()["active_run_id"] is None


async def test_execute_run_pumps_events_and_persists_messages(
    db_session: AsyncSession, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await session_service.create_session(
        db_session, SessionCreate(title="run"), owner_id=TEST_USER_ID
    )
    hub = RenderHub()
    run_id = str(uuid4())
    await run_service_data.start_run_turn(db_session, created.id, user_input="hi", run_id=run_id)
    producer = hub.create(created.id, run_id)
    consumer = hub.subscribe(run_id)
    assert consumer is not None
    resolved = ResolvedModel(
        name="test",
        # BaseAgent 自带工具，而 TestModel 默认把每个工具都调一遍；这里只验文本渲染
        model=TestModel(custom_output_text="你好", call_tools=[]),
        settings={},
        context_window=None,
        supports_tools=False,
    )

    await run_service.execute_run(
        producer=producer,
        session_factory=db_session_factory,
        session_id=created.id,
        run_id=run_id,
        resolved=resolved,
        model_id=None,
    )

    items = await drain(consumer)
    assert any(
        isinstance(item.event, RunStartedEvent) and item.event.run_id == run_id for item in items
    )
    assert any(isinstance(item.event, RunFinishedEvent) for item in items)

    await db_session.refresh(created)
    assert created.active_run_id is None

    rows = list(
        await db_session.scalars(
            select(SessionRun).where(SessionRun.session_id == created.id).order_by(SessionRun.seq)
        )
    )
    assert len(rows) == 1
    texts = [item for item in rows[0].content if isinstance(item, TextItem)]
    assert [item.role for item in texts] == ["user", "assistant"]
    assert hub.subscribe(run_id) is None


async def test_execute_run_marks_message_failed_on_error(
    db_session: AsyncSession, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await session_service.create_session(
        db_session, SessionCreate(title="run"), owner_id=TEST_USER_ID
    )
    hub = RenderHub()
    run_id = str(uuid4())
    await run_service_data.start_run_turn(db_session, created.id, user_input="hi", run_id=run_id)
    producer = hub.create(created.id, run_id)
    consumer = hub.subscribe(run_id)
    assert consumer is not None

    async def boom(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        raise RuntimeError("炸了")
        yield ""  # pragma: no cover

    resolved = ResolvedModel(
        name="bad",
        model=FunctionModel(stream_function=boom),
        settings={},
        context_window=None,
        supports_tools=False,
    )

    await run_service.execute_run(
        producer=producer,
        session_factory=db_session_factory,
        session_id=created.id,
        run_id=run_id,
        resolved=resolved,
        model_id=None,
    )

    items = await drain(consumer)
    assert any(isinstance(item.event, RunErrorEvent) for item in items)

    await db_session.refresh(created)
    assert created.active_run_id is None
    rows = list(
        await db_session.scalars(
            select(SessionRun).where(SessionRun.session_id == created.id).order_by(SessionRun.seq)
        )
    )
    errors = [item for item in rows[0].content if isinstance(item, ErrorItem)]
    assert errors
    assert errors[-1].message == "炸了"
    assert errors[-1].code == "RuntimeError"
    # 半截回答没有，run 里只剩用户文本和 error item
    assert [item.type for item in rows[0].content] == ["text", "error"]
    assert rows[0].status == "failed"


