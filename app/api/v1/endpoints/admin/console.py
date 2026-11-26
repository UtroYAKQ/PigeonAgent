from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import AdminUserDep, OperationLoggerDep, RenderHubDep, SessionDep
from app.core.exceptions import GoneError, UnprocessableError
from app.enums import SessionStatus
from app.infra.files.storage import get_storage
from app.render.queue import RenderCursorInvalid
from app.render.sse import encode_consumer
from app.schemas.admin.console import (
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
from app.schemas.run import SessionRunList, SessionRunRead
from app.services import file_service
from app.services import user as user_service
from app.services.admin import audit
from app.services.admin import service as admin_service
from app.services.billing import service as billing
from app.services.run.tree import branch_navs, path_runs

router = APIRouter(prefix="/admin", tags=["admin"])

SearchQuery = Annotated[str | None, Query(max_length=128)]

_SAFE_INLINE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/x-icon",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
}


def _is_inline_safe(content_type: str | None) -> bool:
    return (content_type or "").lower() in _SAFE_INLINE_TYPES


def _content_headers(name: str, content_type: str, etag: str) -> dict[str, str]:
    encoded = quote(name, safe="")
    safe = _is_inline_safe(content_type)
    disposition = "inline" if safe else "attachment"
    return {
        "Content-Type": content_type if safe else "application/octet-stream",
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}",
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": f'"{etag}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }


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


@router.get("/sessions/{session_id}", response_model=AdminSessionRead)
async def get_session_detail(
    session_id: UUID,
    db: SessionDep,
    user: AdminUserDep,
) -> AdminSessionRead:
    return await admin_service.get_session(db, session_id)


@router.get("/sessions/{session_id}/runs", response_model=SessionRunList)
async def list_session_runs(
    session_id: UUID,
    db: SessionDep,
    user: AdminUserDep,
    before_run_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> SessionRunList:
    """管理端只读会话历史；和用户侧同一套分支分页，只是不做 owner 过滤。"""
    chat_session = await admin_service.load_chat_session(db, session_id)
    runs, has_more = await path_runs(db, session_id, before_run_id=before_run_id, limit=limit)
    branches = await branch_navs(db, session_id, runs, chat_session=chat_session)
    return SessionRunList(
        items=[
            SessionRunRead.model_validate(run).model_copy(update={"branch": branches.get(run.id)})
            for run in runs
        ],
        has_more=has_more,
    )


@router.get("/sessions/{session_id}/runs/{run_id}/events")
async def stream_session_run_events(
    session_id: UUID,
    run_id: str,
    hub: RenderHubDep,
    request: Request,
    db: SessionDep,
    user: AdminUserDep,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """管理员订阅进行中的 run；和用户侧同一条事件流，只读且不校验归属人。"""
    await admin_service.load_chat_session(db, session_id)
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            after = int(last_event_id)
        except ValueError as exc:
            raise UnprocessableError("Last-Event-ID 必须是整数") from exc
    try:
        consumer = await hub.subscribe(run_id, after, session_id=session_id)
    except RenderCursorInvalid as exc:
        raise UnprocessableError(str(exc)) from exc
    if consumer is None:
        raise GoneError(f"Run {run_id} is not streaming")
    return StreamingResponse(
        encode_consumer(consumer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.get("/files/{file_id}/content")
async def read_file_content(
    file_id: UUID,
    db: SessionDep,
    _user: AdminUserDep,
) -> Response:
    storage = get_storage()
    data, name, content_type, etag = await file_service.admin_content_of(db, storage, file_id)
    return Response(content=data, headers=_content_headers(name, content_type, etag))


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
