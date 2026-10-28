from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.enums import SessionStatus
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.schemas.session import SessionCreate, SessionUpdate
from app.services import session_group


async def list_sessions(
    session: AsyncSession,
    *,
    owner_id: UUID,
    limit: int,
    offset: int,
    status: SessionStatus | None = None,
) -> tuple[list[ChatSession], int]:
    # 每个用户只能看到自己的会话；owner 取自令牌，不信任请求体
    count_stmt = select(func.count()).select_from(ChatSession).where(
        ChatSession.owner_id == owner_id
    )
    query = (
        select(ChatSession)
        .where(ChatSession.owner_id == owner_id)
        .order_by(ChatSession.last_run_at.desc(), ChatSession.id)
    )
    if status is not None:
        count_stmt = count_stmt.where(ChatSession.status == status.value)
        query = query.where(ChatSession.status == status.value)
    total = await session.scalar(count_stmt)
    rows = await session.scalars(query.offset(offset).limit(limit))
    return list(rows), total or 0


async def get_session_or_404(
    session: AsyncSession, session_id: UUID, *, owner_id: UUID
) -> ChatSession:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.owner_id != owner_id:
        raise NotFoundError(f"Session {session_id} not found")
    return chat_session


async def create_session(
    session: AsyncSession, payload: SessionCreate, *, owner_id: UUID
) -> ChatSession:
    await _validate_model(session, payload.model_id, owner_id=owner_id)
    await _validate_group(session, payload.group_id, owner_id=owner_id)
    chat_session = ChatSession(
        owner_id=owner_id, title=payload.title, model_id=payload.model_id, group_id=payload.group_id
    )
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


async def update_session(
    session: AsyncSession, session_id: UUID, payload: SessionUpdate, *, owner_id: UUID
) -> ChatSession:
    chat_session = await get_session_or_404(session, session_id, owner_id=owner_id)
    data = payload.model_dump(exclude_unset=True)
    if "model_id" in data:
        await _validate_model(session, data["model_id"], owner_id=owner_id)
    if "group_id" in data:
        await _validate_group(session, data["group_id"], owner_id=owner_id)
    if payload.status is not None:
        data["status"] = payload.status.value
    for field_name, value in data.items():
        setattr(chat_session, field_name, value)
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


async def delete_session(session: AsyncSession, session_id: UUID, *, owner_id: UUID) -> None:
    chat_session = await get_session_or_404(session, session_id, owner_id=owner_id)
    await session.delete(chat_session)
    await session.commit()


async def _validate_group(
    session: AsyncSession, group_id: int | None, *, owner_id: UUID
) -> None:
    if group_id is not None:
        await session_group.get_group_or_404(session, group_id, owner_id=owner_id)


async def _validate_model(
    session: AsyncSession, model_id: int | None, *, owner_id: UUID
) -> None:
    if model_id is None:
        return
    model = await session.get(LlmModel, model_id)
    if model is None or model.owner_id != owner_id:
        raise UnprocessableError(f"Model {model_id} not found")
