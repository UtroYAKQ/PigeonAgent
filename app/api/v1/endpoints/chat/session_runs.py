from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.core.exceptions import ConflictError
from app.db.types import dump_message
from app.domain.run_items import CustomItem
from app.schemas.run import (
    CustomItemCreate,
    SessionContext,
    SessionRunList,
    SessionRunRead,
)
from app.services.chat import session as session_service
from app.services.run.context import build_context
from app.services.run.lease import is_run_live
from app.services.run.store import append_items
from app.services.run.tree import branch_navs, get_run_or_404, path_runs

router = APIRouter(prefix="/sessions", tags=["runs"])


@router.get("/{session_id}/runs", response_model=SessionRunList)
async def list_runs(
    session_id: UUID,
    db: SessionDep,
    user: CurrentUserDep,
    before_run_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> SessionRunList:
    """当前分支的 run（根→叶）。`before_run_id` + `limit` 沿路径向前翻页。"""
    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    runs, has_more = await path_runs(db, session_id, before_run_id=before_run_id, limit=limit)
    branches = await branch_navs(db, session_id, runs, chat_session=chat_session)
    return SessionRunList(
        items=[
            SessionRunRead.model_validate(run).model_copy(update={"branch": branches.get(run.id)})
            for run in runs
        ],
        has_more=has_more,
    )


@router.get("/{session_id}/runs/{run_id}", response_model=SessionRunRead)
async def get_run(
    session_id: UUID, run_id: UUID, db: SessionDep, user: CurrentUserDep
) -> SessionRunRead:
    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    run = await get_run_or_404(db, session_id, run_id)
    branches = await branch_navs(db, session_id, [run], chat_session=chat_session)
    return SessionRunRead.model_validate(run).model_copy(update={"branch": branches.get(run.id)})


@router.post(
    "/{session_id}/runs/{run_id}/items",
    response_model=SessionRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def append_custom_item(
    session_id: UUID,
    run_id: UUID,
    payload: CustomItemCreate,
    db: SessionDep,
    user: CurrentUserDep,
) -> SessionRunRead:
    """手工追加只支持 UI 卡片；卡片永远不进入模型上下文。"""
    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    if is_run_live(chat_session):
        raise ConflictError("运行中的会话不能追加卡片")
    await get_run_or_404(db, session_id, run_id)
    item = CustomItem(
        renderer=payload.renderer,
        version=payload.version,
        data=payload.data,
        key=payload.key,
    )
    run = await append_items(db, session_id, run_id, [item])
    branches = await branch_navs(db, session_id, [run], chat_session=chat_session)
    return SessionRunRead.model_validate(run).model_copy(update={"branch": branches.get(run.id)})


@router.get("/{session_id}/context", response_model=SessionContext)
async def get_context(session_id: UUID, db: SessionDep, user: CurrentUserDep) -> SessionContext:
    """调试用的上下文快照：只拼标签，不下载媒体字节。"""
    await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    result = await build_context(db, session_id, with_media=False)
    return SessionContext(
        runs=[SessionRunRead.model_validate(run) for run in result.runs],
        messages=[dump_message(message) for message in result.messages],
    )
