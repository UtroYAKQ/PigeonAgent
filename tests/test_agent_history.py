import base64
from typing import ClassVar
from uuid import UUID

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    FilePart,
    ImageUrl,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.agents.store import SessionStore
from app.core.exceptions import ConfigurationError
from app.db.types import dump_message, load_message
from app.schemas.run_item import (
    ApprovalRequestItem,
    ImageItem,
    TextItem,
    ToolCallItem,
)
from app.services import item_codec
from app.services import session_run as run_service
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
        session=db_session,
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
    assert item_codec.sum_usage(loaded).requests == 2

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


def test_tool_return_media_round_trips() -> None:
    """工具返回的媒体要能原样回到上下文：bytes 走 jsonable 会变成 repr 字符串，图就废了。"""
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

    item = item_codec.tool_result_item(part)
    assert item.content[1] == {
        "media": "binary",
        "media_type": "image/png",
        "data": base64.b64encode(raw).decode("ascii"),
    }

    rebuilt = item_codec.messages_from_items([item])[0]
    elements = rebuilt.parts[0].content
    assert elements[0] == "截图如下"
    assert isinstance(elements[1], BinaryContent)
    assert elements[1].data == raw
    assert isinstance(elements[2], ImageUrl)
    assert elements[2].url == "https://example.com/a.png"


def test_model_file_part_becomes_display_media_item() -> None:
    """模型直接产出的文件落成媒体 item，只给 UI 看，不参与上下文拼接。"""
    part = FilePart(content=BinaryContent(data=b"abc", media_type="image/png"))

    items = item_codec.items_from_response_part(part)

    assert isinstance(items[0], ImageItem)
    assert items[0].role == "assistant"
    assert items[0].in_context is False
    assert item_codec.messages_from_items(items) == []


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
