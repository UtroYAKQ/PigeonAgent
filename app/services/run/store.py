"""run 写入：建 run、开轮占位、写 item、状态与分支切换。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import codec
from app.core.exceptions import AppError, ConflictError, NotFoundError, UnprocessableError
from app.domain.run_items import (
    ApprovalRequestItem,
    CallRequestItem,
    CompactionItem,
    RunItem,
    TokenUsage,
    ToolResultItem,
)
from app.enums import RunStatus
from app.models.chat.run import SessionRun
from app.models.chat.session import ChatSession
from app.schemas.run import Attachment
from app.services.run.lease import is_run_live, lease_expires_at
from app.services.run.pending import (
    pending_batches,
    pending_batches_from_path,
    sync_pending_count,
)
from app.services.run.tree import get_run_or_404, invalidate_branch_cache
from app.services.run.types import PendingBatch, ResumeDecisions


def _touch_activity(
    chat_session: ChatSession, run: SessionRun, *, now: datetime, usage: TokenUsage | None
) -> None:
    """run 内的一次写入登记到会话：合并 usage、刷新 last_run_at，并给在跑的 run 续租。

    续租是被动的：只延长会话当前已有的租约、从不占用新租约——首次占用是
    start_run_turn 的职责，create_run 建的后台 run 也不该替别的 run 续命，所以那两处不走这里。
    """
    if usage is not None and usage.has_values():
        run.usage = run.usage.merged(usage)
        chat_session.usage = chat_session.usage.merged(usage)
    chat_session.last_run_at = now
    if chat_session.active_run_id is not None:
        chat_session.active_run_expires_at = lease_expires_at(now)


async def append_items(
    db: AsyncSession,
    session_id: UUID,
    run_id: UUID,
    items: Sequence[RunItem],
    *,
    usage: TokenUsage | None = None,
) -> SessionRun:
    if not items and (usage is None or not usage.has_values()):
        return await get_run_or_404(db, session_id, run_id)
    chat_session = await _lock(db, session_id)
    run = await _lock_run(db, session_id, run_id)
    content = [*run.content, *items]
    run.content = content
    run.preview = codec.preview_of(content)
    _touch_activity(chat_session, run, now=datetime.now(UTC), usage=usage)
    if any(
        isinstance(item, (ApprovalRequestItem, CallRequestItem, ToolResultItem)) for item in items
    ):
        # 中断声明与工具结果都落在同一条 run；写入中的 run 就是当前叶子，
        # 祖先分支在开轮时已保证 quiet，所以未决计数只需看这一条 run。
        chat_session.pending_batches = len(pending_batches_from_path([run]))
    await db.commit()
    await db.refresh(run)
    return run


async def record_compaction(
    db: AsyncSession,
    session_id: UUID,
    run_id: UUID,
    item: CompactionItem,
    *,
    usage: TokenUsage | None = None,
) -> SessionRun:
    """压缩结果写在本 run 开头并打上标记；摘要之后才是本轮的用户输入与回答。"""
    chat_session = await _lock(db, session_id)
    run = await _lock_run(db, session_id, run_id)
    run.content = [item, *run.content]
    run.compacted = True
    run.preview = codec.preview_of(run.content)
    _touch_activity(chat_session, run, now=datetime.now(UTC), usage=usage)
    await db.commit()
    await db.refresh(run)
    return run


async def set_run_status(
    db: AsyncSession, session_id: UUID, run_id: UUID, status: RunStatus
) -> None:
    chat_session = await _lock(db, session_id)
    run = await _lock_run(db, session_id, run_id)
    run.status = status.value
    if status is not RunStatus.RUNNING:
        chat_session.has_unread = True
    await db.commit()


async def create_run(
    db: AsyncSession,
    session_id: UUID,
    *,
    run_id: UUID,
    content: Sequence[RunItem] = (),
    parent_run_id: UUID | None = None,
    status: RunStatus = RunStatus.RUNNING,
    model_id: int | None = None,
    usage: TokenUsage | None = None,
    set_leaf: bool = True,
) -> SessionRun:
    chat_session = await _lock(db, session_id)
    if parent_run_id is not None:
        await get_run_or_404(db, session_id, parent_run_id)
    chat_session.run_seq += 1
    now = datetime.now(UTC)
    run = SessionRun(
        id=run_id,
        session_id=session_id,
        parent_run_id=parent_run_id,
        seq=chat_session.run_seq,
        status=status.value,
        content=list(content),
        model_id=model_id,
        preview=codec.preview_of(content),
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()
    # 不走 _touch_activity：create_run 建的 run 不占用会话租约，即便此刻有
    # 在跑的 run 也不替它续命；usage 又是本 run 的第一笔，直接赋值不必 merge
    if usage is not None and usage.has_values():
        run.usage = usage
        chat_session.usage = chat_session.usage.merged(usage)
    chat_session.last_run_at = now
    if set_leaf:
        chat_session.active_leaf_run_id = run.id
        await sync_pending_count(db, chat_session, run.id)
    await db.commit()
    await db.refresh(run)
    invalidate_branch_cache(session_id)
    return run


async def start_run_turn(
    db: AsyncSession,
    session_id: UUID,
    *,
    run_id: str,
    user_input: str | None = None,
    attachments: Sequence[Attachment] = (),
    resource_items: list[RunItem] | None = None,
    retry_run_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    has_explicit_parent: bool = False,
    resume: ResumeDecisions | None = None,
    resume_batch: PendingBatch | None = None,
    model_id: int | None = None,
) -> SessionRun:
    """占用当前 run；resume 直接续写声明批次的那条 run，不再另开一条。

    决策 item 不在这里写：批次要一直算未决，直到承接它的 run 真正跑完。
    """
    chat_session = await _lock(db, session_id)
    if is_run_live(chat_session):
        await _abort(
            db,
            ConflictError(
                f"会话 {session_id} 还有正在运行的轮次",
                active_run_id=chat_session.active_run_id,
            ),
        )

    run_uuid = UUID(run_id)

    if resume is not None:
        target = await _claim_resume(db, chat_session, resume, resume_batch)
        if target != run_uuid:
            await _abort(
                db,
                ConflictError(f"续写必须接在原轮次 {target} 上，而不是 {run_uuid}"),
            )
        run = await _lock_run(db, session_id, run_uuid)
        now = datetime.now(UTC)
        run.status = RunStatus.RUNNING.value
        run.updated_at = now
        if model_id is not None:
            run.model_id = model_id
        chat_session.last_run_at = now
        chat_session.active_leaf_run_id = run.id
        chat_session.active_run_id = run_id
        chat_session.active_run_expires_at = lease_expires_at(now)
        await db.commit()
        await db.refresh(run)
        invalidate_branch_cache(session_id)
        return run

    content: list[RunItem] = []
    parent: UUID | None = None
    if retry_run_id is not None:
        source = await get_run_or_404(db, session_id, retry_run_id)
        content = codec.copied_user_items(source.content)
        if not content:
            await _abort(db, UnprocessableError(f"轮次 {retry_run_id} 没有可重试的用户输入"))
        parent = source.parent_run_id
    else:
        if user_input is None and not attachments and not resource_items:
            await _abort(db, UnprocessableError("本轮没有用户输入"))
        if user_input is not None:
            content.extend(codec.user_items_from_text(user_input))
        content.extend(codec.attachment_items(attachments))
        content.extend(resource_items or [])
        parent = parent_run_id if has_explicit_parent else chat_session.active_leaf_run_id
    await _require_branch_is_quiet(db, session_id, parent)

    chat_session.run_seq += 1
    now = datetime.now(UTC)
    run = SessionRun(
        id=run_uuid,
        session_id=session_id,
        parent_run_id=parent,
        seq=chat_session.run_seq,
        status=RunStatus.RUNNING.value,
        content=content,
        model_id=model_id,
        preview=codec.preview_of(content),
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()
    chat_session.active_leaf_run_id = run.id
    # 不走 _touch_activity：开新轮没有 usage 可合，且这里是首次占用租约——
    # 无条件写 expires，而不是像被动续租那样只在已有租约上延期
    chat_session.last_run_at = now
    chat_session.active_run_id = run_id
    chat_session.active_run_expires_at = lease_expires_at(now)
    # 新轮只在 quiet 分支上开，未决批次必为 0，不用为此扫整条路径
    chat_session.pending_batches = 0
    await db.commit()
    await db.refresh(run)
    invalidate_branch_cache(session_id)
    return run


async def _require_branch_is_quiet(db: AsyncSession, session_id: UUID, parent: UUID | None) -> None:
    """目标分支不能有没回填的 tool call：直接开新轮会让 provider 拒收请求。"""
    if parent is None:
        return
    # pending_batches 只沿这条分支找，有批次就一定压在目标分支上
    if await pending_batches(db, session_id, leaf_id=parent):
        await _abort(
            db,
            ConflictError(f"会话 {session_id} 的当前分支还有未处理的中断，请先恢复"),
        )


async def _claim_resume(
    db: AsyncSession,
    chat_session: ChatSession,
    resume: ResumeDecisions,
    batch: PendingBatch | None,
) -> UUID:
    if batch is None:
        await _abort(
            db,
            ConflictError(f"中断批次 {resume.interrupt_id} 不是未决状态"),
        )
    if batch.interrupt_id != resume.interrupt_id:
        await _abort(
            db,
            ConflictError(f"中断批次 {resume.interrupt_id} 不是未决状态"),
        )
    known = {item.tool_call_id: item for item in batch.interrupts}
    for call_id in [*resume.approvals, *resume.calls]:
        if call_id not in known:
            await _abort(db, UnprocessableError(f"工具调用 {call_id} 不是未决状态"))
    missing = [
        item.tool_call_id
        for item in batch.interrupts
        if item.tool_call_id not in (resume.approvals if item.kind == "approval" else resume.calls)
    ]
    if missing:
        await _abort(
            db,
            UnprocessableError(f"续写必须覆盖所有未决中断；缺少 {', '.join(missing)}"),
        )
    # resume 的 run 从声明批次的那条 run 接着长
    chat_session.active_leaf_run_id = batch.run_id
    return batch.run_id


async def switch_leaf(db: AsyncSession, session_id: UUID, leaf_run_id: UUID | None) -> ChatSession:
    """切换当前分支；被放弃的分支留在库里，只是不再进上下文。"""
    chat_session = await _lock(db, session_id)
    if is_run_live(chat_session):
        await _abort(db, ConflictError(f"会话 {session_id} 还有正在运行的轮次"))
    if leaf_run_id is not None:
        await get_run_or_404(db, session_id, leaf_run_id)
    chat_session.active_leaf_run_id = leaf_run_id
    await sync_pending_count(db, chat_session, leaf_run_id)
    await db.commit()
    invalidate_branch_cache(session_id)
    return chat_session


async def _lock(db: AsyncSession, session_id: UUID) -> ChatSession:
    chat_session = await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id).with_for_update()
    )
    if chat_session is None:
        await _abort(db, NotFoundError(f"会话 {session_id} 不存在"))
    return chat_session


async def _lock_run(db: AsyncSession, session_id: UUID, run_id: UUID) -> SessionRun:
    run = await db.scalar(
        select(SessionRun)
        .where(SessionRun.id == run_id, SessionRun.session_id == session_id)
        .with_for_update()
    )
    if run is None:
        await _abort(db, NotFoundError(f"轮次 {run_id} 不存在"))
    return run


async def _abort(db: AsyncSession, error: AppError) -> NoReturn:
    """写路径失败先回滚，别把 FOR UPDATE 的行锁留在请求会话里。"""
    await db.rollback()
    raise error
