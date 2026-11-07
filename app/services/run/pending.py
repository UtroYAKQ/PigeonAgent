"""未决中断批次：扫描、按分支计数与同步。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.run_items import (
    ApprovalRequestItem,
    CallRequestItem,
    PendingInterrupt,
    ToolResultItem,
)
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.services.run.tree import load_by_ids, path_ids
from app.services.run.types import PendingBatch


def pending_batches_from_path(runs: Sequence[SessionRun]) -> list[PendingBatch]:
    """沿一条 run 路径找 request 还没有 ToolResultItem 的中断批次。"""
    batch_run: dict[UUID, SessionRun] = {}
    requests: defaultdict[UUID, list[PendingInterrupt]] = defaultdict(list)
    resolved = {
        item.tool_call_id
        for run in runs
        for item in run.content
        if isinstance(item, ToolResultItem)
    }
    for run in runs:
        for item in run.content:
            if isinstance(item, ApprovalRequestItem):
                batch_run.setdefault(item.interrupt_id, run)
                requests[item.interrupt_id].extend(
                    PendingInterrupt(
                        interrupt_id=item.interrupt_id,
                        tool_call_id=call_id,
                        kind="approval",
                    )
                    for call_id in item.tool_call_ids
                )
            elif isinstance(item, CallRequestItem):
                batch_run.setdefault(item.interrupt_id, run)
                requests[item.interrupt_id].extend(
                    PendingInterrupt(
                        interrupt_id=item.interrupt_id,
                        tool_call_id=call_id,
                        kind="call",
                    )
                    for call_id in item.tool_call_ids
                )
    pending: list[PendingBatch] = []
    for interrupt_id, interrupts in requests.items():
        unresolved = [item for item in interrupts if item.tool_call_id not in resolved]
        if not unresolved:
            continue
        run = batch_run[interrupt_id]
        pending.append(
            PendingBatch(
                run_id=run.id,
                run_seq=run.seq,
                interrupt_id=interrupt_id,
                interrupts=unresolved,
            )
        )
    return pending


async def pending_batches(
    db: AsyncSession, session_id: UUID, *, leaf_id: UUID | None = None
) -> list[PendingBatch]:
    """当前分支上 request 还没有对应 response 的中断批次。"""
    chat_session = await db.get(ChatSession, session_id)
    leaf = leaf_id or (chat_session.active_leaf_run_id if chat_session else None)
    return await _pending_for_leaf(db, session_id, leaf)


async def _pending_for_leaf(
    db: AsyncSession, session_id: UUID, leaf: UUID | None
) -> list[PendingBatch]:
    if leaf is None:
        return []
    ids = await path_ids(db, session_id, leaf)
    return pending_batches_from_path(await load_by_ids(db, ids))


async def sync_pending_count(
    db: AsyncSession,
    chat_session: ChatSession,
    leaf: UUID | None,
) -> None:
    """按目标分支重算计数；调用方负责事务提交。"""
    batches = await _pending_for_leaf(db, chat_session.id, leaf)
    chat_session.pending_batches = len(batches)
