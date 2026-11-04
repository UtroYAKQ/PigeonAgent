from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.enums import SessionStatus, ThinkingLevel
from app.models.llm_model import LlmModel
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.session import SessionCreate, SessionUpdate
from app.services import session_group


async def list_sessions(
    db: AsyncSession,
    *,
    owner_id: UUID,
    limit: int,
    offset: int,
    status: SessionStatus | None = None,
    q: str | None = None,
) -> tuple[list[ChatSession], int]:
    # 每个用户只能看到自己的会话；owner 取自令牌，不信任请求体
    count_stmt = (
        select(func.count()).select_from(ChatSession).where(ChatSession.owner_id == owner_id)
    )
    query = (
        select(ChatSession)
        .where(ChatSession.owner_id == owner_id)
        .order_by(ChatSession.last_run_at.desc(), ChatSession.id)
    )
    if status is not None:
        count_stmt = count_stmt.where(ChatSession.status == status.value)
        query = query.where(ChatSession.status == status.value)
    keyword = (q or "").strip()
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        title_match = ChatSession.title.ilike(pattern, escape="\\")
        preview_match = (
            select(SessionRun.id)
            .where(
                SessionRun.session_id == ChatSession.id,
                SessionRun.preview.ilike(pattern, escape="\\"),
            )
            .exists()
        )
        condition = or_(title_match, preview_match)
        count_stmt = count_stmt.where(condition)
        query = query.where(condition)
    total = await db.scalar(count_stmt)
    rows = await db.scalars(query.offset(offset).limit(limit))
    return list(rows), total or 0


async def get_session_or_404(db: AsyncSession, session_id: UUID, *, owner_id: UUID) -> ChatSession:
    chat_session = await db.get(ChatSession, session_id)
    if chat_session is None or chat_session.owner_id != owner_id:
        raise NotFoundError(f"Session {session_id} not found")
    return chat_session


async def create_session(
    db: AsyncSession, payload: SessionCreate, *, owner_id: UUID
) -> ChatSession:
    model = await _validate_model(db, payload.model_id)
    await _validate_group(db, payload.group_id, owner_id=owner_id)
    if payload.thinking_level is not None:
        _require_supported_thinking_level(model or await _default_model(db), payload.thinking_level)
    chat_session = ChatSession(
        owner_id=owner_id,
        title=payload.title,
        model_id=payload.model_id,
        group_id=payload.group_id,
        thinking_level=payload.thinking_level.value if payload.thinking_level else None,
    )
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def update_session(
    db: AsyncSession, session_id: UUID, payload: SessionUpdate, *, owner_id: UUID
) -> ChatSession:
    chat_session = await get_session_or_404(db, session_id, owner_id=owner_id)
    data = payload.model_dump(exclude_unset=True)
    next_model = (
        await db.get(LlmModel, chat_session.model_id) if chat_session.model_id is not None else None
    )
    if "model_id" in data:
        next_model = await _validate_model(db, data["model_id"])
    if "group_id" in data:
        await _validate_group(db, data["group_id"], owner_id=owner_id)
    explicit_level = "thinking_level" in payload.model_fields_set
    if explicit_level and payload.thinking_level is not None:
        # 早期/接口创建的会话可能没有绑定 model_id；挡位按默认模型校验，
        # 否则前端明明显示了挡位菜单，却被“未选择模型”拒掉。
        _require_supported_thinking_level(
            next_model or await _default_model(db), payload.thinking_level
        )
        data["thinking_level"] = payload.thinking_level.value
    elif not explicit_level and next_model is not None and chat_session.thinking_level:
        # 换到不支持当前挡位的模型时安静回落到默认，避免历史会话把 run 卡死
        supported = {level for level in next_model.thinking_levels}
        if chat_session.thinking_level not in supported:
            data["thinking_level"] = None
    if payload.status is not None:
        data["status"] = payload.status.value
    for field_name, value in data.items():
        setattr(chat_session, field_name, value)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def mark_session_read(db: AsyncSession, session_id: UUID, *, owner_id: UUID) -> ChatSession:
    chat_session = await get_session_or_404(db, session_id, owner_id=owner_id)
    if not chat_session.has_unread:
        return chat_session
    chat_session.has_unread = False
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def delete_session(db: AsyncSession, session_id: UUID, *, owner_id: UUID) -> None:
    chat_session = await get_session_or_404(db, session_id, owner_id=owner_id)
    await db.delete(chat_session)
    await db.commit()


async def _validate_group(db: AsyncSession, group_id: int | None, *, owner_id: UUID) -> None:
    if group_id is not None:
        await session_group.get_group_or_404(db, group_id, owner_id=owner_id)


async def _validate_model(db: AsyncSession, model_id: int | None) -> LlmModel | None:
    """模型是全局共享的：只校验存在，不再按会话归属过滤。"""
    if model_id is None:
        return None
    model = await db.get(LlmModel, model_id)
    if model is None:
        raise UnprocessableError(f"Model {model_id} not found")
    return model


async def _default_model(db: AsyncSession) -> LlmModel | None:
    return await db.scalar(
        select(LlmModel)
        .where(LlmModel.is_active.is_(True))
        .order_by(LlmModel.is_default.desc(), LlmModel.id)
        .limit(1)
    )


def _require_supported_thinking_level(model: LlmModel | None, level: ThinkingLevel) -> None:
    if model is None or level.value not in model.thinking_levels:
        label = model.name if model is not None else "未选择模型"
        raise UnprocessableError(f"Model '{label}' does not support thinking level '{level.value}'")
