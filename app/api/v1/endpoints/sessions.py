from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.enums import SessionStatus
from app.models.session import ChatSession
from app.schemas.run import PendingBatchRead
from app.schemas.run_item import TokenUsage
from app.schemas.session import (
    LeafSwitch,
    SessionCreate,
    SessionList,
    SessionRead,
    SessionUpdate,
)
from app.services import chat_session as session_service
from app.services import session_run as run_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate, session: SessionDep, user: CurrentUserDep
) -> ChatSession:
    return await session_service.create_session(session, payload, owner_id=user.id)


@router.get("", response_model=SessionList)
async def list_sessions(
    session: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session_status: Annotated[SessionStatus | None, Query(alias="status")] = None,
) -> SessionList:
    items, total = await session_service.list_sessions(
        session,
        owner_id=user.id,
        limit=limit,
        offset=offset,
        status=session_status,
    )
    counts = await run_service.pending_counts(session, [item.id for item in items])
    return SessionList(
        items=[
            SessionRead.model_validate(item).model_copy(
                update={"pending_batches": counts.get(item.id, 0)}
            )
            for item in items
        ],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: UUID, session: SessionDep, user: CurrentUserDep
) -> SessionRead:
    chat_session = await session_service.get_session_or_404(
        session, session_id, owner_id=user.id
    )
    # server onupdate 字段可能处于 expired 状态，序列化前先加载回来
    await session.refresh(chat_session)
    counts = await run_service.pending_counts(session, [session_id])
    return SessionRead.model_validate(chat_session).model_copy(
        update={"pending_batches": counts.get(session_id, 0)}
    )


@router.patch("/{session_id}", response_model=SessionRead)
async def update_session(
    session_id: UUID, payload: SessionUpdate, session: SessionDep, user: CurrentUserDep
) -> ChatSession:
    return await session_service.update_session(session, session_id, payload, owner_id=user.id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID, session: SessionDep, user: CurrentUserDep
) -> None:
    await session_service.delete_session(session, session_id, owner_id=user.id)


@router.post("/{session_id}/leaf", response_model=SessionRead)
async def switch_leaf(
    session_id: UUID, payload: LeafSwitch, session: SessionDep, user: CurrentUserDep
) -> ChatSession:
    """切换当前分支；被放弃的分支留在库里，只是不再进上下文。"""
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    chat_session = await run_service.switch_leaf(session, session_id, payload.leaf_run_id)
    # UPDATE 后 server onupdate 字段处于 expired 状态，先异步加载再序列化
    await session.refresh(chat_session)
    return chat_session


@router.get("/{session_id}/pending", response_model=list[PendingBatchRead])
async def list_pending(
    session_id: UUID, session: SessionDep, user: CurrentUserDep
) -> list[PendingBatchRead]:
    """各分支上未决的中断批次；每条带它挂在哪条 run 上。"""
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    batches = await run_service.pending_batches(session, session_id)
    return [
        PendingBatchRead(
            run_id=batch.run_id,
            run_seq=batch.run_seq,
            interrupt_id=batch.interrupt_id,
            interrupts=batch.interrupts,
        )
        for batch in batches
    ]


@router.get("/{session_id}/usage", response_model=TokenUsage)
async def get_session_usage(
    session_id: UUID, session: SessionDep, user: CurrentUserDep
) -> TokenUsage:
    await session_service.get_session_or_404(session, session_id, owner_id=user.id)
    return await run_service.usage_summary(session, session_id)
