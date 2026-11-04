from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUserDep, OperationLoggerDep, SessionDep
from app.enums import SessionStatus
from app.schemas.admin import (
    AdminChatLogList,
    AdminCreditAdjustIn,
    AdminCreditLogList,
    AdminOperationLogList,
    AdminPasswordResetIn,
    AdminSessionList,
    AdminSessionRead,
    AdminSessionUpdate,
    AdminStatsRead,
    AdminUserList,
    AdminUserRead,
    AdminUserUpdate,
)
from app.services import admin as admin_service
from app.services import audit, billing
from app.services import user as user_service

router = APIRouter(prefix="/admin", tags=["admin"])

SearchQuery = Annotated[str | None, Query(max_length=128)]


@router.get("/stats", response_model=AdminStatsRead)
async def get_stats(db: SessionDep, user: AdminUserDep) -> AdminStatsRead:
    return await admin_service.stats(db)


@router.get("/users", response_model=AdminUserList)
async def list_users(
    db: SessionDep,
    user: AdminUserDep,
    q: SearchQuery = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserList:
    return await admin_service.list_users(db, q=q, limit=limit, offset=offset)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    db: SessionDep,
    user: AdminUserDep,
) -> AdminUserRead:
    updated = await admin_service.update_user(db, user, user_id, payload)
    await audit.record(
        actor=user,
        action=audit.USER_UPDATE,
        target_type="user",
        target_id=str(user_id),
        detail=payload.model_dump(exclude_unset=True),
    )
    return updated


@router.post("/users/{user_id}/credits", response_model=AdminUserRead)
async def adjust_user_credits(
    user_id: UUID,
    payload: AdminCreditAdjustIn,
    db: SessionDep,
    user: AdminUserDep,
) -> AdminUserRead:
    await billing.adjust(db, user_id=user_id, delta=payload.delta, note=payload.note)
    await audit.record(
        actor=user,
        action=audit.USER_CREDIT_ADJUST,
        target_type="user",
        target_id=str(user_id),
        detail={"delta": payload.delta, "note": payload.note},
    )
    return await admin_service.get_user(db, user_id)


@router.get("/credits/logs", response_model=AdminCreditLogList)
async def list_credit_logs(
    db: SessionDep,
    user: AdminUserDep,
    user_id: UUID | None = None,
    reason: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminCreditLogList:
    return await admin_service.list_credit_logs(
        db, user_id=user_id, reason=reason, limit=limit, offset=offset
    )


@router.get("/chat-logs", response_model=AdminChatLogList)
async def list_chat_logs(
    db: SessionDep,
    user: AdminUserDep,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(max_length=16, alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminChatLogList:
    return await admin_service.list_chat_logs(
        db,
        user_id=user_id,
        session_id=session_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_user_password(
    user_id: UUID,
    payload: AdminPasswordResetIn,
    db: SessionDep,
    user: AdminUserDep,
) -> None:
    await user_service.reset_password(
        db, user_id, actor_id=user.id, new_password=payload.new_password
    )
    await audit.record(
        actor=user,
        action=audit.USER_PASSWORD_RESET,
        target_type="user",
        target_id=str(user_id),
    )


@router.get("/sessions", response_model=AdminSessionList)
async def list_sessions(
    db: SessionDep,
    user: AdminUserDep,
    q: SearchQuery = None,
    status: Annotated[SessionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminSessionList:
    return await admin_service.list_sessions(db, q=q, status=status, limit=limit, offset=offset)


@router.patch("/sessions/{session_id}", response_model=AdminSessionRead)
async def update_session(
    session_id: UUID,
    payload: AdminSessionUpdate,
    db: SessionDep,
    user: AdminUserDep,
) -> AdminSessionRead:
    updated = await admin_service.update_session_status(db, session_id, payload.status)
    await audit.record(
        actor=user,
        action=audit.SESSION_UPDATE,
        target_type="session",
        target_id=str(session_id),
        detail={"status": payload.status.value},
    )
    return updated


@router.get("/logs", response_model=AdminOperationLogList)
async def list_logs(
    db: SessionDep,
    user: AdminUserDep,
    operation_logger: OperationLoggerDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    q: SearchQuery = None,
    method: Annotated[str | None, Query(max_length=10)] = None,
    status_code: Annotated[int | None, Query(ge=100, le=599, alias="status")] = None,
    kind: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminOperationLogList:
    # 队列里还没落库的那几条也要出现在这次查询里
    if operation_logger is not None:
        await operation_logger.flush()
    return await admin_service.list_logs(
        db,
        action=action,
        q=q,
        method=method,
        status_code=status_code,
        kind=kind,
        limit=limit,
        offset=offset,
    )
