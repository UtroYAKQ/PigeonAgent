from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, SessionDep, SettingsDep
from app.enums import SessionStatus
from app.models.session import ChatSession
from app.sandbox.workspace import purge_session_workspace
from app.schemas.run import PendingBatchRead
from app.schemas.session import (
    LeafSwitch,
    SessionCreate,
    SessionList,
    SessionRead,
    SessionUpdate,
)
from app.services import chat_session as session_service
from app.services import run_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _read_back(db: AsyncSession, chat_session: ChatSession) -> SessionRead:
    """把服务端写的字段读回来再序列化。

    连接工厂是 expire_on_commit=False，UPDATE 的 onupdate 值（updated_at）
    不会自动回到 Python 对象；不 refresh 就会把改动前的时间戳回给前端。
    """
    await db.refresh(chat_session)
    return SessionRead.model_validate(chat_session)


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate, db: SessionDep, user: CurrentUserDep
) -> SessionRead:
    # INSERT 时服务端默认值已经随 flush 取回，不必再 refresh 一次
    chat_session = await session_service.create_session(db, payload, owner_id=user.id)
    return SessionRead.model_validate(chat_session)


@router.get("", response_model=SessionList)
async def list_sessions(
    db: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session_status: Annotated[SessionStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> SessionList:
    items, total = await session_service.list_sessions(
        db,
        owner_id=user.id,
        limit=limit,
        offset=offset,
        status=session_status,
        q=q,
    )
    return SessionList(
        items=[SessionRead.model_validate(item) for item in items],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(session_id: UUID, db: SessionDep, user: CurrentUserDep) -> SessionRead:
    chat_session = await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    return await _read_back(db, chat_session)


@router.patch("/{session_id}", response_model=SessionRead)
async def update_session(
    session_id: UUID, payload: SessionUpdate, db: SessionDep, user: CurrentUserDep
) -> SessionRead:
    chat_session = await session_service.update_session(db, session_id, payload, owner_id=user.id)
    return await _read_back(db, chat_session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID, db: SessionDep, user: CurrentUserDep, settings: SettingsDep
) -> None:
    await session_service.delete_session(db, session_id, owner_id=user.id)
    # 本地模式的工作区目录按会话存，会话没了目录就该回收（沙箱那边由 pool 负责）
    await purge_session_workspace(settings, session_id)


@router.post("/{session_id}/read", response_model=SessionRead)
async def mark_session_read(session_id: UUID, db: SessionDep, user: CurrentUserDep) -> SessionRead:
    chat_session = await session_service.mark_session_read(db, session_id, owner_id=user.id)
    return await _read_back(db, chat_session)


@router.post("/{session_id}/leaf", response_model=SessionRead)
async def switch_leaf(
    session_id: UUID, payload: LeafSwitch, db: SessionDep, user: CurrentUserDep
) -> SessionRead:
    """切换当前分支；被放弃的分支留在库里，只是不再进上下文。"""
    await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    chat_session = await run_store.switch_leaf(db, session_id, payload.leaf_run_id)
    return await _read_back(db, chat_session)


@router.get("/{session_id}/pending", response_model=list[PendingBatchRead])
async def list_pending(
    session_id: UUID, db: SessionDep, user: CurrentUserDep
) -> list[PendingBatchRead]:
    """各分支上未决的中断批次；每条带它挂在哪条 run 上。"""
    await session_service.get_session_or_404(db, session_id, owner_id=user.id)
    batches = await run_store.pending_batches(db, session_id)
    return [
        PendingBatchRead(
            run_id=batch.run_id,
            run_seq=batch.run_seq,
            interrupt_id=batch.interrupt_id,
            interrupts=batch.interrupts,
        )
        for batch in batches
    ]
