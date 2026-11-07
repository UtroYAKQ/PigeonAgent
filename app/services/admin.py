"""平台管理查询：统计、用户、会话和操作日志。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.enums import RunStatus, SessionStatus
from app.models.chat_request_log import ChatRequestLog
from app.models.credit_ledger import CreditLedger
from app.models.operation_log import OperationLog
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.models.user import User
from app.schemas.admin import (
    AdminChatLogList,
    AdminChatLogRead,
    AdminCreditLogList,
    AdminCreditLogRead,
    AdminOperationLogList,
    AdminOperationLogRead,
    AdminSessionList,
    AdminSessionRead,
    AdminStatsRead,
    AdminUserList,
    AdminUserRead,
    AdminUserUpdate,
)


async def _count(db: AsyncSession, statement: Select[int]) -> int:
    value = await db.scalar(statement)
    return int(value or 0)


async def stats(db: AsyncSession) -> AdminStatsRead:
    return AdminStatsRead(
        users_total=await _count(db, select(func.count()).select_from(User)),
        users_active=await _count(
            db, select(func.count()).select_from(User).where(User.is_active.is_(True))
        ),
        users_admin=await _count(
            db, select(func.count()).select_from(User).where(User.is_admin.is_(True))
        ),
        sessions_total=await _count(db, select(func.count()).select_from(ChatSession)),
        sessions_active=await _count(
            db,
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.status == SessionStatus.ACTIVE.value),
        ),
        sessions_archived=await _count(
            db,
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.status == SessionStatus.ARCHIVED.value),
        ),
        runs_total=await _count(db, select(func.count()).select_from(SessionRun)),
        runs_failed=await _count(
            db,
            select(func.count())
            .select_from(SessionRun)
            .where(SessionRun.status == RunStatus.FAILED.value),
        ),
    )


def _user_columns() -> tuple[Any, Any]:
    session_count = (
        select(func.count(ChatSession.id)).where(ChatSession.owner_id == User.id).scalar_subquery()
    )
    last_active_at = (
        select(func.max(ChatSession.last_run_at))
        .where(ChatSession.owner_id == User.id)
        .scalar_subquery()
    )
    return session_count, last_active_at


async def list_users(db: AsyncSession, *, q: str | None, limit: int, offset: int) -> AdminUserList:
    session_count, last_active_at = _user_columns()
    statement = select(
        User,
        session_count.label("session_count"),
        last_active_at.label("last_active_at"),
    )
    count_statement = select(func.count()).select_from(User)
    query = (q or "").strip()
    if query:
        condition = or_(
            User.email.ilike(f"%{query}%"),
            User.display_name.ilike(f"%{query}%"),
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    total = int(await db.scalar(count_statement) or 0)
    rows = (
        await db.execute(
            statement.order_by(User.created_at.desc(), User.email).offset(offset).limit(limit)
        )
    ).all()
    items = [
        _to_admin_user(user, session_count_value, last_active_value)
        for user, session_count_value, last_active_value in rows
    ]
    return AdminUserList(items=items, total=total)


def _to_admin_user(
    user: User, session_count: int | None, last_active_at: datetime | None
) -> AdminUserRead:
    """会话数和最后活跃时间是子查询附加列，不在 User 行上。"""
    return AdminUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        email_verified=user.email_verified,
        created_at=user.created_at,
        session_count=int(session_count or 0),
        last_active_at=last_active_at,
        credits_balance=user.credits_balance,
    )


async def _user_row_or_404(db: AsyncSession, user_id: uuid.UUID) -> tuple[User, int | None, Any]:
    session_count, last_active_at = _user_columns()
    row = (
        await db.execute(
            select(
                User,
                session_count.label("session_count"),
                last_active_at.label("last_active_at"),
            ).where(User.id == user_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(f"User {user_id} not found")
    return cast("tuple[User, int | None, Any]", row)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> AdminUserRead:
    user, session_count, last_active_at = await _user_row_or_404(db, user_id)
    return _to_admin_user(user, session_count, last_active_at)


async def update_user(
    db: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
) -> AdminUserRead:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError(f"User {user_id} not found")
    data = payload.model_dump(exclude_unset=True)
    if target.id == actor.id and (data.get("is_admin") is False or data.get("is_active") is False):
        raise UnprocessableError("不能停用自己或取消自己的管理员权限")
    if "display_name" in data:
        value = data["display_name"]
        data["display_name"] = value.strip() if value else None
    for field_name, value in data.items():
        setattr(target, field_name, value)
    await db.commit()
    return await get_user(db, user_id)


def _session_columns() -> Any:
    run_count = (
        select(func.count(SessionRun.id))
        .where(SessionRun.session_id == ChatSession.id)
        .scalar_subquery()
    )
    return run_count


def _to_admin_session(
    chat_session: ChatSession,
    owner_email: str | None,
    owner_display_name: str | None,
    run_count: int,
) -> AdminSessionRead:
    return AdminSessionRead(
        id=chat_session.id,
        title=chat_session.title,
        owner_id=chat_session.owner_id,
        owner_email=owner_email,
        owner_display_name=owner_display_name,
        status=SessionStatus(chat_session.status),
        model_id=chat_session.model_id,
        has_unread=chat_session.has_unread,
        active_run_id=chat_session.active_run_id,
        usage=chat_session.usage,
        run_count=int(run_count or 0),
        last_run_at=chat_session.last_run_at,
        created_at=chat_session.created_at,
    )


async def list_sessions(
    db: AsyncSession,
    *,
    q: str | None,
    status: SessionStatus | None,
    limit: int,
    offset: int,
) -> AdminSessionList:
    run_count = _session_columns()
    statement = select(
        ChatSession,
        User.email,
        User.display_name,
        run_count.label("run_count"),
    ).outerjoin(User, User.id == ChatSession.owner_id)
    count_statement = (
        select(func.count())
        .select_from(ChatSession)
        .outerjoin(User, User.id == ChatSession.owner_id)
    )
    query = (q or "").strip()
    if query:
        condition = or_(
            ChatSession.title.ilike(f"%{query}%"),
            User.email.ilike(f"%{query}%"),
            User.display_name.ilike(f"%{query}%"),
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    if status is not None:
        statement = statement.where(ChatSession.status == status.value)
        count_statement = count_statement.where(ChatSession.status == status.value)
    total = int(await db.scalar(count_statement) or 0)
    rows = (
        await db.execute(
            statement.order_by(ChatSession.last_run_at.desc()).offset(offset).limit(limit)
        )
    ).all()
    items = [
        _to_admin_session(chat_session, owner_email, owner_name, run_count_value)
        for chat_session, owner_email, owner_name, run_count_value in rows
    ]
    return AdminSessionList(items=items, total=total)


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> AdminSessionRead:
    run_count = _session_columns()
    row = (
        await db.execute(
            select(
                ChatSession,
                User.email,
                User.display_name,
                run_count.label("run_count"),
            )
            .outerjoin(User, User.id == ChatSession.owner_id)
            .where(ChatSession.id == session_id)
        )
    ).first()
    if row is None:
        raise NotFoundError(f"会话 {session_id} 不存在")
    chat_session, owner_email, owner_name, run_count_value = row
    return _to_admin_session(chat_session, owner_email, owner_name, run_count_value)


async def update_session_status(
    db: AsyncSession, session_id: uuid.UUID, status: SessionStatus
) -> AdminSessionRead:
    chat_session = await db.get(ChatSession, session_id)
    if chat_session is None:
        raise NotFoundError("会话不存在")
    if status == SessionStatus.ARCHIVED and chat_session.active_run_id:
        raise UnprocessableError("运行中的会话不能归档")
    chat_session.status = status.value
    await db.commit()
    return await get_session(db, session_id)


async def list_logs(
    db: AsyncSession,
    *,
    action: str | None,
    q: str | None,
    method: str | None,
    status_code: int | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> AdminOperationLogList:
    statement = select(OperationLog)
    count_statement = select(func.count()).select_from(OperationLog)
    conditions = []
    if action:
        conditions.append(OperationLog.action == action)
    if method:
        conditions.append(OperationLog.method == method.upper())
    if status_code is not None:
        conditions.append(OperationLog.status_code == status_code)
    if kind:
        conditions.append(OperationLog.kind == kind)
    query = (q or "").strip()
    if query:
        conditions.append(
            or_(
                OperationLog.actor_email.ilike(f"%{query}%"),
                OperationLog.path.ilike(f"%{query}%"),
                OperationLog.route.ilike(f"%{query}%"),
                OperationLog.request_id.ilike(f"%{query}%"),
                OperationLog.target_id.ilike(f"%{query}%"),
                OperationLog.action.ilike(f"%{query}%"),
            )
        )
    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    total = int(await db.scalar(count_statement) or 0)
    rows = await db.scalars(
        statement.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return AdminOperationLogList(
        items=[AdminOperationLogRead.model_validate(row) for row in rows],
        total=total,
    )


async def list_credit_logs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    reason: str | None,
    limit: int,
    offset: int,
) -> AdminCreditLogList:
    statement = (
        select(CreditLedger, User.email, User.display_name)
        .outerjoin(User, User.id == CreditLedger.user_id)
        .order_by(CreditLedger.created_at.desc())
    )
    count_statement = select(func.count()).select_from(CreditLedger)
    if user_id is not None:
        statement = statement.where(CreditLedger.user_id == user_id)
        count_statement = count_statement.where(CreditLedger.user_id == user_id)
    if reason:
        statement = statement.where(CreditLedger.reason == reason)
        count_statement = count_statement.where(CreditLedger.reason == reason)
    total = int(await db.scalar(count_statement) or 0)
    rows = (await db.execute(statement.offset(offset).limit(limit))).all()
    items = []
    for ledger, email, display_name in rows:
        item = AdminCreditLogRead.model_validate(ledger)
        item.user_email = email
        item.user_display_name = display_name
        items.append(item)
    return AdminCreditLogList(items=items, total=total)


async def list_chat_logs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> AdminChatLogList:
    statement = (
        select(ChatRequestLog, User.email, User.display_name)
        .outerjoin(User, User.id == ChatRequestLog.user_id)
        .order_by(ChatRequestLog.created_at.desc())
    )
    count_statement = select(func.count()).select_from(ChatRequestLog)
    if user_id is not None:
        statement = statement.where(ChatRequestLog.user_id == user_id)
        count_statement = count_statement.where(ChatRequestLog.user_id == user_id)
    if session_id is not None:
        statement = statement.where(ChatRequestLog.session_id == session_id)
        count_statement = count_statement.where(ChatRequestLog.session_id == session_id)
    if status:
        statement = statement.where(ChatRequestLog.status == status)
        count_statement = count_statement.where(ChatRequestLog.status == status)
    total = int(await db.scalar(count_statement) or 0)
    rows = (await db.execute(statement.offset(offset).limit(limit))).all()
    items = []
    for log, email, display_name in rows:
        item = AdminChatLogRead.model_validate(log)
        item.user_email = email
        item.user_display_name = display_name
        items.append(item)
    return AdminChatLogList(items=items, total=total)
