"""测试共用的 run / item 脚手架。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from pydantic_ai.messages import (
    DeferredToolRequests,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run_item import (
    PendingInterrupts,
    RunItem,
    TextItem,
    ToolCallItem,
)
from app.schemas.session import SessionCreate
from app.services import chat_session as session_service
from app.services import item_codec
from app.services import session_run as run_service
from tests.conftest import TEST_USER_ID


def user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def assistant(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def texts_of(messages: Sequence[ModelMessage]) -> list[str]:
    return [
        str(content)
        for message in messages
        for part in message.parts
        if (content := getattr(part, "content", None)) is not None
    ]


async def make_session(db_session: AsyncSession, title: str = "测试会话", **kwargs: Any) -> UUID:
    owner_id = kwargs.pop("owner_id", TEST_USER_ID)
    created = await session_service.create_session(
        db_session, SessionCreate(title=title, **kwargs), owner_id=owner_id
    )
    return created.id


async def head(db_session: AsyncSession, session_id: UUID) -> ChatSession:
    chat_session = await db_session.get(ChatSession, session_id)
    assert chat_session is not None
    await db_session.refresh(chat_session)
    return chat_session


async def path(db_session: AsyncSession, session_id: UUID) -> list[SessionRun]:
    """当前分支上的 run（根→叶）。"""
    runs, _ = await run_service.path_runs(db_session, session_id)
    return runs


async def all_runs(db_session: AsyncSession, session_id: UUID) -> list[SessionRun]:
    rows = await db_session.scalars(
        select(SessionRun).where(SessionRun.session_id == session_id).order_by(SessionRun.seq)
    )
    return list(rows)


def items_of(run: SessionRun, kind: type[Any]) -> list[Any]:
    return [item for item in run.content if isinstance(item, kind)]


async def append_run(
    db_session: AsyncSession,
    session_id: UUID,
    messages: Sequence[ModelMessage],
    *,
    parent_run_id: UUID | None = None,
    status: str = "completed",
) -> SessionRun:
    """把一组消息拆成 item，建成一个 run；默认接在当前叶子后面。"""
    content: list[RunItem] = []
    for message in messages:
        content.extend(item_codec.items_from_message(message))
    chat_session = await head(db_session, session_id)
    parent = parent_run_id if parent_run_id is not None else chat_session.active_leaf_run_id
    return await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=content,
        parent_run_id=parent,
        status=RunStatus(status),
    )


async def append_user_run(
    db_session: AsyncSession,
    session_id: UUID,
    text: str,
    *,
    parent_run_id: UUID | None = None,
) -> SessionRun:
    chat_session = await head(db_session, session_id)
    parent = parent_run_id if parent_run_id is not None else chat_session.active_leaf_run_id
    return await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=[TextItem(role="user", text=text)],
        parent_run_id=parent,
    )


def approval_call(tool_call_id: str = "call_1", tool: str = "delete_file") -> ToolCallPart:
    return ToolCallPart(tool, '{"path": "a.txt"}', tool_call_id)


def price_call(tool_call_id: str = "call_2") -> ToolCallPart:
    return ToolCallPart("fetch_price", '{"symbol": "AAA"}', tool_call_id)


async def declare_pending(
    db_session: AsyncSession,
    session_id: UUID,
    calls: list[ToolCallPart],
    *,
    text: str = "要执行吗",
) -> tuple[SessionRun, PendingInterrupts]:
    """建一个 run：用户提问 + 带中断声明的 tool call。"""
    chat_session = await head(db_session, session_id)
    content: list[RunItem] = [
        TextItem(role="user", text=text),
        *[
            ToolCallItem(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=item_codec.jsonable(call.args),
            )
            for call in calls
        ],
    ]
    run = await run_service.create_run(
        db_session,
        session_id,
        run_id=uuid4(),
        content=content,
        parent_run_id=chat_session.active_leaf_run_id,
        status=RunStatus.INTERRUPTED,
    )
    await run_service.append_items(
        db_session,
        session_id,
        run.id,
        item_codec.to_request_items(
            DeferredToolRequests(
                approvals=[call for call in calls if call.tool_name == "delete_file"],
                calls=[call for call in calls if call.tool_name != "delete_file"],
            )
        ),
    )
    batches = await run_service.pending_batches(db_session, session_id)
    batch = next(item for item in batches if item.run_id == run.id)
    return run, batch.interrupts


async def pending(db_session: AsyncSession, session_id: UUID) -> list[Any]:
    return await run_service.pending_batches(db_session, session_id)
