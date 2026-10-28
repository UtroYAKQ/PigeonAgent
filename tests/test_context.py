"""上下文拼接：run 路径、item 的 in_context 开关。"""

from uuid import uuid4

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.run_item import ApprovalRequestItem, TextItem, ToolResultItem
from app.services import session_run as run_service
from tests.helpers import (
    append_run,
    assistant,
    make_session,
    path,
    texts_of,
    user,
)


async def test_context_returns_full_path(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    first = await append_run(db_session, session_id, [user("问题一"), assistant("回答一")])
    second = await append_run(db_session, session_id, [user("问题二"), assistant("回答二")])

    context = await run_service.build_context(db_session, session_id)

    assert [run.id for run in context.runs] == [first.id, second.id]
    assert texts_of(context.messages) == ["问题一", "回答一", "问题二", "回答二"]


async def test_orphan_tool_result_keeps_its_slot(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await append_run(
        db_session,
        session_id,
        [
            user("问题"),
            ModelRequest(parts=[ToolReturnPart("read", "output", "call_1")]),
        ],
    )

    context = await run_service.build_context(db_session, session_id)

    assert texts_of(context.messages) == ["问题", "output"]


async def test_approval_and_custom_items_stay_out_of_context(
    db_session: AsyncSession,
) -> None:
    session_id = await make_session(db_session)
    call = ToolCallPart("delete_file", '{"path": "a.txt"}', "call_1")
    run = await append_run(
        db_session,
        session_id,
        [user("删掉文件"), ModelResponse(parts=[call])],
    )
    await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[
            ApprovalRequestItem(interrupt_id=uuid4(), tool_call_ids=["call_1"]),
            ToolResultItem(tool_call_id="call_1", tool_name="delete_file", content="deleted"),
        ],
        parent_run_id=run.id,
    )

    context = await run_service.build_context(db_session, session_id)

    assert "deleted" in texts_of(context.messages)


async def test_in_context_and_display_are_independent(db_session: AsyncSession) -> None:
    session_id = await make_session(db_session)
    await append_run(
        db_session,
        session_id,
        [user("问题"), assistant("可见于上下文")],
    )
    await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[
            TextItem(role="user", text="只在 UI 显示", in_context=False, display=True),
            TextItem(role="user", text="只进上下文", in_context=True, display=False),
        ],
        parent_run_id=(await path(db_session, session_id))[-1].id,
    )

    context = await run_service.build_context(db_session, session_id)

    assert "只进上下文" in texts_of(context.messages)
    assert "只在 UI 显示" not in texts_of(context.messages)
