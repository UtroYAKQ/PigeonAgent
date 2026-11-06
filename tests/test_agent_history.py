import base64
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    FilePart,
    ImageUrl,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import codec
from app.agents.base import BaseAgent
from app.agents.store import SessionStore
from app.core.exceptions import ConfigurationError
from app.db.types import dump_message, load_message
from app.domain.run_items import (
    ApprovalRequestItem,
    TextItem,
    TokenUsage,
    ToolCallItem,
    ToolResultItem,
)
from app.enums import RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services import run_store as run_service
from tests.helpers import (
    append_run,
    assistant,
    declare_pending,
    items_of,
    make_session,
    path,
    user,
)


class HistoryAgent(BaseAgent):
    name: ClassVar[str] = "history"
    instructions: ClassVar[str] = "你是测试助手。"


def make_agent(
    db_session: AsyncSession | None,
    session_id: UUID | None,
    *,
    output: str = "好的",
) -> HistoryAgent:
    return HistoryAgent(
        TestModel(custom_output_text=output, call_tools=[]),
        db=db_session,
        session_id=session_id,
    )


async def test_new_session_has_empty_history(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)

    messages = await SessionStore(db_session, session_id).load()

    assert messages == []


async def test_run_persists_one_run_with_user_and_assistant(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id, output="收到")

    result = await agent.run("你好")

    assert result.output == "收到"

    runs = await path(db_session, session_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed"
    assert [item.role for item in items_of(run, TextItem)] == ["user", "assistant"]
    assert run.usage.requests == 1
    assert run.usage.input_tokens > 0


async def test_history_accumulates_across_turns(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)

    await agent.run("第一轮")
    await agent.run("第二轮")

    loaded = await SessionStore(db_session, session_id).load()
    assert len(loaded) == 4
    assert codec.sum_usage(loaded).requests == 2

    runs = await path(db_session, session_id)
    assert [run.seq for run in runs] == [1, 2]
    assert runs[1].parent_run_id == runs[0].id


async def test_history_requires_binding() -> None:
    agent = make_agent(None, None)

    with pytest.raises(ConfigurationError):
        agent.agui_events("hi")


async def test_conversation_round_trips_through_items(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    agent = make_agent(db_session, session_id)
    await agent.run("带工具的一轮")

    loaded = await SessionStore(db_session, session_id).load()
    dumped = dump_message(loaded[0])
    restored = load_message(dumped)

    assert restored == loaded[0]
    assert isinstance(loaded[0].parts[0], UserPromptPart)


def test_tool_result_marks_failure_from_error_payload() -> None:
    """工具吞掉异常返回 error / 非零 exit_code 时，失败要落到 outcome 字段。"""
    error_part = ToolReturnPart(
        tool_name="read_file",
        content={"error": "沙箱里读不到 missing.md"},
        tool_call_id="call_1",
    )
    command_part = ToolReturnPart(
        tool_name="run_command",
        content={"exit_code": 1, "stdout": "", "stderr": "failed"},
        tool_call_id="call_2",
    )
    ok_part = ToolReturnPart(
        tool_name="run_command",
        content={"exit_code": 0, "stdout": "ok", "stderr": ""},
        tool_call_id="call_3",
    )

    assert codec.tool_result_item(error_part).outcome == "failed"
    assert codec.tool_result_item(command_part).outcome == "failed"
    assert codec.tool_result_item(ok_part).outcome == "success"


def test_failed_tool_result_round_trips_error_message() -> None:
    """失败结果重建上下文时只保留错误文案，避免再包一层转义 JSON。"""
    item = codec.tool_result_item(
        ToolReturnPart(
            tool_name="read_file",
            content={"error": "沙箱里读不到 missing.md"},
            tool_call_id="call_1",
        )
    )
    rebuilt = codec.messages_from_items([item])[0]
    part = rebuilt.parts[0]
    assert isinstance(part, ToolReturnPart)
    assert part.outcome == "failed"
    assert part.content == "沙箱里读不到 missing.md"


def test_tool_return_media_round_trips() -> None:
    """工具返回的媒体要能原样回到上下文：bytes 走 to_json_value 会变成 repr 字符串，图就废了。"""
    raw = b"\x89PNG\xff\x00"
    part = ToolReturnPart(
        tool_name="shot",
        content=[
            "截图如下",
            BinaryContent(data=raw, media_type="image/png"),
            ImageUrl(url="https://example.com/a.png"),
        ],
        tool_call_id="call_1",
    )

    item = codec.tool_result_item(part)
    assert item.content[1] == {
        "media": "binary",
        "media_type": "image/png",
        "data": base64.b64encode(raw).decode("ascii"),
    }

    rebuilt = codec.messages_from_items([item])[0]
    elements = rebuilt.parts[0].content
    assert elements[0] == "截图如下"
    assert isinstance(elements[1], BinaryContent)
    assert elements[1].data == raw
    assert isinstance(elements[2], ImageUrl)
    assert elements[2].url == "https://example.com/a.png"


def test_imported_media_without_file_id_is_ignored() -> None:
    """导入路径拿不到 file_id：统一媒体模型下不再落 url/base64 形态。"""
    message = ModelRequest(
        parts=[UserPromptPart(content=["看图", BinaryContent(data=b"png", media_type="image/png")])]
    )
    items = codec.items_from_message(message)
    assert [item.type for item in items] == ["text"]


def test_model_file_parts_are_ignored_without_upload() -> None:
    """模型原生二进制没有 file_id，不再以 base64 落库。"""
    part = FilePart(content=BinaryContent(data=b"abc", media_type="image/png"))
    assert codec.items_from_response_part(part) == []


async def test_store_buffers_items_until_status_flush(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    session_id = await make_session(db_session)
    store = SessionStore(
        db_session,
        session_id,
        session_factory=db_session_factory,
        run_id=str(uuid4()),
    )
    await store.ensure_run("你好")
    await store.append_items([TextItem(role="assistant", text="批量内容")])

    run = await db_session.get(SessionRun, store.run_uuid)
    assert run is not None
    await db_session.refresh(run)
    assert all(
        not (getattr(item, "type", None) == "text" and getattr(item, "role", None) == "assistant")
        for item in run.content
    )

    await store.set_status(RunStatus.COMPLETED)
    await db_session.refresh(run)
    assert any(
        getattr(item, "type", None) == "text"
        and getattr(item, "role", None) == "assistant"
        and getattr(item, "text", None) == "批量内容"
        for item in run.content
    )


async def test_dangling_tool_call_gets_synthetic_result(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await append_run(
        db_session,
        session_id,
        [user("查一下"), assistant("")],
    )
    # 直接补一个只有 tool call 的 run，模拟半截历史
    run = await run_service.create_run(
        db_session,
        session_id,
        run_id=__import__("uuid").uuid4(),
        content=[
            ToolCallItem(
                tool_call_id="call-1",
                tool_name="fetch",
                args={"url": "x"},
            )
        ],
        parent_run_id=(await path(db_session, session_id))[-1].id,
    )
    assert run.id

    loaded = await SessionStore(db_session, session_id).load()

    returns = [
        part for message in loaded for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert returns
    assert returns[-1].tool_call_id == "call-1"
    assert returns[-1].content == "No result provided"


async def test_pending_interrupts_are_declared_on_run_items(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    call = ToolCallPart("delete_file", '{"path": "a.txt"}', "call_1")
    run, interrupts = await declare_pending(db_session, session_id, [call])

    reloaded = await run_service.get_run_or_404(db_session, session_id, run.id)
    calls = items_of(reloaded, ToolCallItem)
    assert [item.tool_call_id for item in calls] == ["call_1"]
    requests = items_of(reloaded, ApprovalRequestItem)
    assert len(requests) == 1
    assert requests[0].interrupt_id == interrupts[0].interrupt_id
    assert requests[0].tool_call_ids == ["call_1"]
    # 中断描述符只留 id：工具参数仍然只在 ToolCallItem 里
    assert set(interrupts[0].model_dump()) == {"interrupt_id", "tool_call_id", "kind"}

    batches = await run_service.pending_batches(db_session, session_id)
    assert [batch.run_id for batch in batches] == [run.id]
    assert [item.kind for item in batches[0].interrupts] == ["approval"]
    chat_session = await db_session.get(ChatSession, session_id)
    assert chat_session is not None and chat_session.pending_batches == 1

    await run_service.append_items(
        db_session,
        session_id,
        run.id,
        [
            ToolResultItem(
                tool_call_id="call_1",
                tool_name="delete_file",
                content="ok",
                outcome="denied",
            )
        ],
    )
    await db_session.refresh(chat_session)
    assert chat_session.pending_batches == 0


async def test_store_notifies_usage_observer_after_flush(
    db_session: AsyncSession, db_session_factory: Any
) -> None:
    """带用量的落库成功后要通知观察者（计费熔断挂在这里）；观察者出错不炸对话。"""
    session_id = await make_session(db_session)
    seen: list[TokenUsage] = []

    async def observer(usage: TokenUsage) -> None:
        seen.append(usage)

    store = SessionStore(
        db_session,
        session_id,
        session_factory=db_session_factory,
        run_id=str(uuid4()),
        on_usage=observer,
    )
    await store.ensure_run("你好")
    await store.append_items(
        [TextItem(role="assistant", text="回答")],
        usage=TokenUsage(input_tokens=100, output_tokens=20),
    )
    assert len(seen) == 1
    assert seen[0].total_tokens == 120

    # 观察者抛异常不能影响落库
    async def broken(usage: TokenUsage) -> None:
        raise RuntimeError("boom")

    broken_store = SessionStore(
        db_session,
        session_id,
        session_factory=db_session_factory,
        run_id=str(uuid4()),
        on_usage=broken,
    )
    await broken_store.ensure_run("你好")
    await broken_store.append_items(
        [TextItem(role="assistant", text="回答")],
        usage=TokenUsage(input_tokens=1),
    )
    run = await db_session.get(SessionRun, broken_store.run_uuid)
    assert run is not None
    assert run.usage.total_tokens == 1
