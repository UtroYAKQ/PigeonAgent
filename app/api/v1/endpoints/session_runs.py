from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.core.exceptions import ConflictError
from app.db.types import dump_message
from app.schemas.run import (
    SessionContext,
    SessionRunList,
    SessionRunRead,
)
from app.schemas.run_item import CustomItem
from app.services import chat_session as session_service
from app.services import session_run as run_service

router = APIRouter(prefix="/sessions", tags=["runs"])


@router.get("/{session_id}/runs", response_model=SessionRunList)
async def list_runs(
    session_id: UUID,
    session: SessionDep,
    user: CurrentUserDep,
    before_run_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> SessionRunList:
    """当前分支的 run（根→叶）。`before_run_id` + `limit` 沿路径向前翻页。"""
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    runs, has_more = await run_service.path_runs(
        session, session_id, before_run_id=before_run_id, limit=limit
    )
    branches = await run_service.branch_navs(session, session_id, runs)
    return SessionRunList(
        items=[
            SessionRunRead.model_validate(run).model_copy(update={"branch": branches.get(run.id)})
            for run in runs
        ],
        has_more=has_more,
    )


@router.get("/{session_id}/runs/{run_id}", response_model=SessionRunRead)
async def get_run(
    session_id: UUID, run_id: UUID, session: SessionDep, user: CurrentUserDep
) -> SessionRunRead:
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    run = await run_service.get_run_or_404(session, session_id, run_id)
    return SessionRunRead.model_validate(run)


@router.post(
    "/{session_id}/runs/{run_id}/items",
    response_model=SessionRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def append_custom_item(
    session_id: UUID,
    run_id: UUID,
    payload: CustomItem,
    session: SessionDep,
    user: CurrentUserDep,
) -> SessionRunRead:
    """手工追加只支持 UI 卡片；卡片永远不进入模型上下文。"""
    chat_session = await session_service.get_session_or_404(
        session, session_id, owner_id=user.id
    )
    if run_service.run_is_live(chat_session):
        raise ConflictError("Cannot append an item while a run is active")
    await run_service.get_run_or_404(session, session_id, run_id)
    item = payload.model_copy(update={"in_context": False})
    run = await run_service.append_items(session, session_id, run_id, [item])
    return SessionRunRead.model_validate(run)


@router.get("/{session_id}/context", response_model=SessionContext)
async def get_context(
    session_id: UUID, session: SessionDep, user: CurrentUserDep
) -> SessionContext:
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    result = await run_service.build_context(session, session_id)
    return SessionContext(
        runs=[SessionRunRead.model_validate(run) for run in result.runs],
        messages=[dump_message(message) for message in result.messages],
    )
