"""AG-UI 流、审批恢复、取消/异常半截回答的 run/item 落库。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, ClassVar
from uuid import UUID

from ag_ui.core import (
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    ToolCallStartEvent,
)
from pydantic_ai import (
    CancellationToken,
    DeferredToolResults,
    Tool,
    ToolApproved,
    ToolDenied,
    ToolReturn,
)
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.tools import frontend_toolset
from app.schemas.run import FrontendTool
from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    ErrorItem,
    TextItem,
    ThinkingItem,
    ToolCallItem,
    ToolResultItem,
)
from app.schemas.session import SessionCreate
from app.services import chat_session as session_service
from app.services import session_run as run_service
from tests.conftest import TEST_USER_ID
from tests.helpers import all_runs, path

DANGEROUS_TOOL = "delete_file"


async def slow_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    for char in ["半", "截", "内", "容"]:
        await asyncio.sleep(0.05)
        yield char


async def failing_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
    yield "半截"
    raise RuntimeError("模型炸了")


async def slow_tool_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[dict[int, DeltaToolCall]]:
    yield {0: DeltaToolCall(name="delete_file", json_args='{"path": "al', tool_call_id="call_slow")}
    while True:
        await asyncio.sleep(0.05)
        yield {0: DeltaToolCall(json_args="pha", tool_call_id="call_slow")}


async def slow_thinking_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[dict[int, DeltaThinkingPart]]:
    index = 0
    while True:
        yield {0: DeltaThinkingPart(content=f"思{index}")}
        index += 1
        await asyncio.sleep(0.05)


class ApprovalAgent(BaseAgent):
    name: ClassVar[str] = "approval-demo"
    instructions: ClassVar[str] = "危险操作必须先申请人工审批。"

    def default_tools(self) -> list[Tool[Any]]:
        def delete_file(path: str) -> str:
            return f"deleted {path}"

        return [
            Tool(
                delete_file,
                name=DANGEROUS_TOOL,
                description="删除文件，需要人工审批",
                requires_approval=True,
            )
        ]


class CardAgent(BaseAgent):
    name: ClassVar[str] = "card-demo"

    def default_tools(self) -> list[Tool[Any]]:
        async def show_card(title: str) -> ToolReturn:
            return ToolReturn(
                return_value="card shown",
                metadata=[
                    StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={"card": title}),
                    CustomEvent(type=EventType.CUSTOM, name="card", value={"title": title}),
                ],
            )

        return [Tool(show_card, name="show_card", description="显示一张卡片")]


async def make_session(db_session: AsyncSession) -> UUID:
    created = await session_service.create_session(
        db_session, SessionCreate(title="AG-UI 测试"), owner_id=TEST_USER_ID
    )
    return created.id


def make_agent(db_session: AsyncSession, session_id: UUID) -> ApprovalAgent:
    return ApprovalAgent(TestModel(), session=db_session, session_id=session_id)


async def drain(stream: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in stream]


def items_of(run: Any, kind: type[Any]) -> list[Any]:
    return [item for item in run.content if isinstance(item, kind)]


async def pending_of(db_session: AsyncSession, session_id: UUID) -> list[Any]:
    return await run_service.pending_batches(db_session, session_id)


def pending_call_ids(batches: list[Any], kind: str | None = None) -> list[str]:
    return [
        item.tool_call_id
        for batch in batches
        for item in batch.interrupts
        if kind is None or item.kind == kind
    ]


async def test_tool_interrupt_emits_agui_events_and_stores_items(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)

    events = await drain(agent.agui_events("删掉 a.txt"))

    assert isinstance(events[0], RunStartedEvent)
    assert any(isinstance(event, ToolCallStartEvent) for event in events)
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    interrupts = getattr(finished.outcome, "interrupts", None)
    assert interrupts, "AG-UI 原生中断未产生"

    runs = await all_runs(db_session, session_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "interrupted"
    calls = items_of(run, ToolCallItem)
    assert calls[0].tool_call_id == interrupts[0].tool_call_id
    assert calls[0].tool_name == DANGEROUS_TOOL
    requests = items_of(run, ApprovalRequestItem)
    assert len(requests) == 1
    assert requests[0].tool_call_ids == [calls[0].tool_call_id]
    pending = await pending_of(db_session, session_id)
    assert pending_call_ids(pending, "approval") == [calls[0].tool_call_id]
    assert [batch.run_id for batch in pending] == [run.id]


async def test_resume_after_approval_finishes_and_persists(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)
    events = await drain(agent.agui_events("删掉 a.txt"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    interrupts = getattr(finished.outcome, "interrupts", None)
    assert interrupts
    call_id = interrupts[0].tool_call_id

    resume = DeferredToolResults(approvals={call_id: ToolApproved()})
    events = await drain(agent.agui_events(None, deferred_tool_results=resume))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert getattr(finished.outcome, "interrupts", None) is None

    runs = await path(db_session, session_id)
    assert len(runs) == 2
    resume_run = runs[-1]
    assert resume_run.parent_run_id == runs[0].id
    assert items_of(resume_run, ToolResultItem)
    assert items_of(resume_run, ToolResultItem)[0].tool_call_id == call_id
    assert items_of(resume_run, TextItem)
    assert await pending_of(db_session, session_id) == []


async def test_agui_cancel_saves_partial_answer(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = BaseAgent(
        FunctionModel(stream_function=slow_stream),
        session=db_session,
        session_id=session_id,
    )
    token = CancellationToken()
    events: list[Any] = []
    first_text = asyncio.Event()

    async def consume() -> None:
        async for event in agent.agui_events("写一段", cancellation_token=token):
            events.append(event)
            if isinstance(event, TextMessageContentEvent):
                first_text.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_text.wait(), timeout=5)
    token.cancel()
    await asyncio.wait_for(task, timeout=5)

    assert events
    runs = await all_runs(db_session, session_id)
    texts = items_of(runs[-1], TextItem)
    assert any("半" in item.text and item.in_context is False for item in texts)
    assert runs[-1].status == "cancelled"


async def test_agui_cancel_saves_partial_tool_call(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = ApprovalAgent(
        FunctionModel(stream_function=slow_tool_stream),
        session=db_session,
        session_id=session_id,
    )
    token = CancellationToken()
    started = asyncio.Event()

    async def consume() -> None:
        async for event in agent.agui_events("写一段", cancellation_token=token):
            if isinstance(event, ToolCallStartEvent):
                started.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=5)
    token.cancel()
    await asyncio.wait_for(task, timeout=5)

    runs = await all_runs(db_session, session_id)
    partials = [
        item for item in runs[-1].content if isinstance(item, ToolCallItem) and not item.in_context
    ]
    assert len(partials) == 1, "半截工具调用只落一次"
    assert partials[0].tool_name == DANGEROUS_TOOL
    assert str(partials[0].args).startswith('{"path": "al'), "增量参数要累计起来"
    assert runs[-1].status == "cancelled"


async def test_agui_cancel_saves_partial_thinking(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = BaseAgent(
        FunctionModel(stream_function=slow_thinking_stream),
        session=db_session,
        session_id=session_id,
    )
    token = CancellationToken()

    async def consume() -> None:
        async for _ in agent.agui_events("想清楚再答", cancellation_token=token):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.25)
    token.cancel()
    await asyncio.wait_for(task, timeout=5)

    runs = await all_runs(db_session, session_id)
    partials = [
        item for item in runs[-1].content if isinstance(item, ThinkingItem) and not item.in_context
    ]
    assert partials and partials[0].text.startswith("思0思1"), "半截思考要按增量累计"
    assert runs[-1].status == "cancelled"


async def test_agui_error_emits_event_and_saves_partial(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = BaseAgent(
        FunctionModel(stream_function=failing_stream),
        session=db_session,
        session_id=session_id,
    )

    events = await drain(agent.agui_events("写一段"))

    assert any(isinstance(event, RunErrorEvent) for event in events)
    runs = await all_runs(db_session, session_id)
    assert items_of(runs[-1], ErrorItem)
    partials = [
        item for item in runs[-1].content if isinstance(item, TextItem) and "半截" in item.text
    ]
    assert len(partials) == 1, "半截回答只能落一次"
    failure = items_of(runs[-1], ErrorItem)[-1]
    assert failure.message == "模型炸了"
    assert failure.code == "RuntimeError"


async def test_tool_return_metadata_streams_and_persists(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = CardAgent(TestModel(), session=db_session, session_id=session_id)

    events = await drain(agent.agui_events("显示卡片"))

    custom = next(
        event for event in events if isinstance(event, CustomEvent) and event.name == "card"
    )
    assert "title" in custom.value

    runs = await all_runs(db_session, session_id)
    tool_result = next(
        item
        for item in runs[-1].content
        if isinstance(item, ToolResultItem) and item.tool_name == "show_card"
    )
    assert [event["type"] for event in tool_result.metadata] == ["STATE_SNAPSHOT", "CUSTOM"]
    assert "title" in tool_result.metadata[1]["value"]


async def test_dynamic_approval_can_be_denied(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)

    def run_sql(query: str) -> str:
        raise ApprovalRequired()

    agent = BaseAgent(
        TestModel(),
        session=db_session,
        session_id=session_id,
        tools=[Tool(run_sql, name="run_sql")],
    )
    events = await drain(agent.agui_events("执行查询"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    interrupts = getattr(finished.outcome, "interrupts", None)
    assert interrupts
    call_id = interrupts[0].tool_call_id
    resume = DeferredToolResults(approvals={call_id: ToolDenied(message="不允许执行")})
    await drain(agent.agui_events(None, deferred_tool_results=resume))

    runs = await path(db_session, session_id)
    results = [item for run in runs for item in items_of(run, ToolResultItem)]
    assert any("不允许执行" in str(part.content) for part in results)
    assert await pending_of(db_session, session_id) == []


async def test_override_args_is_applied(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    executed: list[str] = []

    def write_file(path: str) -> str:
        executed.append(path)
        return f"wrote {path}"

    agent = BaseAgent(
        TestModel(),
        session=db_session,
        session_id=session_id,
        tools=[Tool(write_file, name="write_file", requires_approval=True)],
    )
    events = await drain(agent.agui_events("写文件"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    interrupts = getattr(finished.outcome, "interrupts", None)
    assert interrupts
    call_id = interrupts[0].tool_call_id
    resume = DeferredToolResults(approvals={call_id: ToolApproved(override_args={"path": "b.txt"})})
    await drain(agent.agui_events(None, deferred_tool_results=resume))

    assert executed == ["b.txt"]
    runs = await path(db_session, session_id)
    results = [item for run in runs for item in items_of(run, ToolResultItem)]
    assert any("b.txt" in str(item.content) for item in results)
    assert await pending_of(db_session, session_id) == []


async def test_external_call_pending_and_resumed(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)

    def fetch_price(symbol: str) -> str:
        raise CallDeferred(metadata={"source": "vendor"})

    agent = BaseAgent(
        TestModel(),
        session=db_session,
        session_id=session_id,
        tools=[Tool(fetch_price, name="fetch_price")],
    )
    await drain(agent.agui_events("查价格"))

    pending_state = await pending_of(db_session, session_id)
    call_ids = pending_call_ids(pending_state, "call")
    assert len(call_ids) == 1
    call_id = call_ids[0]
    runs = await all_runs(db_session, session_id)
    requests = items_of(runs[-1], CallRequestItem)
    assert requests[0].metadata == {call_id: {"source": "vendor"}}

    resume = DeferredToolResults(
        calls={call_id: "100 USD"},
        metadata={call_id: {"trace": "abc"}},
    )
    await drain(agent.agui_events(None, deferred_tool_results=resume))

    results = [
        item for run in await path(db_session, session_id) for item in items_of(run, ToolResultItem)
    ]
    assert any("100 USD" in str(item.content) for item in results)
    assert await pending_of(db_session, session_id) == []


PREVIEW_TOOL = FrontendTool(
    name="ui_open_html_preview",
    description="在浏览器里渲染 HTML 并打开预览",
    parameters={
        "type": "object",
        "properties": {"title": {"type": "string"}, "html": {"type": "string"}},
        "required": ["html"],
    },
)


async def preview_tool_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[dict[int, DeltaToolCall]]:
    yield {
        0: DeltaToolCall(
            name="ui_open_html_preview",
            json_args='{"title": "报表", "html": "<h1>ok</h1>"}',
            tool_call_id="call_preview",
        )
    }


async def test_frontend_tool_defers_to_call_and_resumes(db_session: AsyncSession) -> None:
    """浏览器声明的工具后端不注册：模型调用它落成 Call 中断，结果由 resume 回填。"""
    session_id = await make_session(db_session)
    agent = BaseAgent(
        FunctionModel(stream_function=preview_tool_stream),
        session=db_session,
        session_id=session_id,
    )
    toolsets = [frontend_toolset([PREVIEW_TOOL])]

    await drain(agent.agui_events("预览一下", toolsets=toolsets))

    runs = await all_runs(db_session, session_id)
    assert [item.tool_call_ids for item in items_of(runs[-1], CallRequestItem)] == [
        ["call_preview"]
    ]
    assert await pending_of(db_session, session_id)

    await drain(
        agent.agui_events(
            None,
            deferred_tool_results=DeferredToolResults(calls={"call_preview": "已打开预览"}),
            toolsets=toolsets,
        )
    )

    results = [
        item for run in await path(db_session, session_id) for item in items_of(run, ToolResultItem)
    ]
    assert any("已打开预览" in str(item.content) for item in results)
    assert await pending_of(db_session, session_id) == []
