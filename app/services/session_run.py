"""run 树的写入、上下文拼接、中断与压缩窗口。

run 用 parent_run_id 组树，`sessions.active_leaf_run_id` 指向当前分支末端。
当前分支就是从叶子往根的那条链，所以上下文、分页和重新生成都按路径走。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from sqlalchemy import func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased as orm_aliased

from app.core.exceptions import AppError, ConflictError, NotFoundError, UnprocessableError
from app.enums import RunKind, RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run import Attachment, BranchNav
from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    ImageItem,
    PendingInterrupt,
    PendingInterrupts,
    RunItem,
    TokenUsage,
    ToolResultItem,
    VideoItem,
)
from app.services import file_service, item_codec

# worker 崩了会话也不会永久卡住；正常跑着的 run 靠心跳续租
RUN_LEASE_SECONDS = 600


@dataclass(slots=True)
class ResumeDecisions:
    interrupt_id: UUID
    approvals: dict[str, bool] = field(default_factory=dict)
    calls: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingBatch:
    run_id: UUID
    run_seq: int
    interrupt_id: UUID
    interrupts: PendingInterrupts


@dataclass(slots=True)
class BuiltContext:
    runs: list[SessionRun]
    messages: list[ModelMessage]


# ------------------------------------------------------------------ 读取


async def path_ids(session: AsyncSession, session_id: UUID, leaf_id: UUID) -> list[UUID]:
    """从叶子递归走到根，返回根→叶顺序的 run id。"""
    leaf = orm_aliased(SessionRun)
    anchor = (
        select(
            leaf.id.label("id"),
            leaf.parent_run_id.label("parent_run_id"),
            literal(0).label("depth"),
        )
        .where(leaf.id == leaf_id, leaf.session_id == session_id)
        .cte("run_path", recursive=True)
    )
    parent = orm_aliased(SessionRun)
    depth_cap = await session.scalar(
        select(func.count()).select_from(SessionRun).where(SessionRun.session_id == session_id)
    )
    step = select(
        parent.id.label("id"),
        parent.parent_run_id.label("parent_run_id"),
        (anchor.c.depth + 1).label("depth"),
    ).where(
        parent.id == anchor.c.parent_run_id,
        parent.session_id == session_id,
        anchor.c.depth < int(depth_cap or 0),
    )
    path = anchor.union_all(step)
    rows = await session.execute(select(path.c.id, path.c.depth).order_by(path.c.depth.desc()))
    return [row[0] for row in rows]


async def load_by_ids(session: AsyncSession, ids: Sequence[UUID]) -> list[SessionRun]:
    if not ids:
        return []
    rows = await session.scalars(select(SessionRun).where(SessionRun.id.in_(list(ids))))
    by_id = {row.id: row for row in rows}
    return [by_id[item] for item in ids if item in by_id]


async def branch_navs(
    session: AsyncSession, session_id: UUID, runs: Sequence[SessionRun]
) -> dict[UUID, BranchNav]:
    """给当前页的 turn run 算分支版本和各自的末端；children 只需要一次扁平查询。"""
    if not any(run.kind == RunKind.TURN.value for run in runs):
        return {}
    rows = (
        await session.execute(
            select(SessionRun.id, SessionRun.parent_run_id, SessionRun.kind, SessionRun.seq)
            .where(SessionRun.session_id == session_id)
            .order_by(SessionRun.seq)
        )
    ).all()
    kinds = {row.id: row.kind for row in rows}
    children: dict[UUID | None, list[UUID]] = {}
    for row in rows:
        children.setdefault(row.parent_run_id, []).append(row.id)

    tips: dict[UUID, UUID] = {}

    def tip(run_id: UUID) -> UUID:
        path: list[UUID] = []
        current = run_id
        while current not in tips:
            path.append(current)
            kids = children.get(current)
            if not kids:
                tips[current] = current
                break
            current = kids[-1]
        for node in path:
            tips[node] = tips[current]
        return tips[current]

    navs: dict[UUID, BranchNav] = {}
    for run in runs:
        if run.kind != RunKind.TURN.value:
            continue
        siblings = [
            run_id
            for run_id in children.get(run.parent_run_id, [])
            if kinds[run_id] == RunKind.TURN.value
        ]
        if len(siblings) < 2:
            continue
        navs[run.id] = BranchNav(
            position=siblings.index(run.id) + 1,
            total=len(siblings),
            leaves=[tip(run_id) for run_id in siblings],
        )
    return navs


async def path_runs(
    session: AsyncSession,
    session_id: UUID,
    *,
    leaf_id: UUID | None = None,
    limit: int | None = None,
    before_run_id: UUID | None = None,
) -> tuple[list[SessionRun], bool]:
    """当前分支的 run（根→叶）。返回 (这一页, 更早的还有没有)。"""
    chat_session = await session.get(ChatSession, session_id)
    leaf_id = leaf_id or (chat_session.active_leaf_run_id if chat_session else None)
    if leaf_id is None:
        return [], False
    ids = await path_ids(session, session_id, leaf_id)
    if before_run_id is not None and before_run_id in ids:
        ids = ids[: ids.index(before_run_id)]
    has_more = limit is not None and len(ids) > limit
    if limit is not None:
        ids = ids[-limit:]
    return await load_by_ids(session, ids), has_more


async def get_run_or_404(session: AsyncSession, session_id: UUID, run_id: UUID) -> SessionRun:
    run = await session.scalar(
        select(SessionRun).where(SessionRun.id == run_id, SessionRun.session_id == session_id)
    )
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    return run


def _pending_batches_from_path(runs: Sequence[SessionRun]) -> list[PendingBatch]:
    """沿一条 run 路径找 request 还没有 ToolResultItem 的中断批次。"""
    batch_run: dict[UUID, SessionRun] = {}
    requests: dict[UUID, list[PendingInterrupt]] = {}
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
                requests.setdefault(item.interrupt_id, []).extend(
                    PendingInterrupt(
                        interrupt_id=item.interrupt_id,
                        tool_call_id=call_id,
                        kind="approval",
                    )
                    for call_id in item.tool_call_ids
                )
            elif isinstance(item, CallRequestItem):
                batch_run.setdefault(item.interrupt_id, run)
                requests.setdefault(item.interrupt_id, []).extend(
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
    session: AsyncSession, session_id: UUID, *, leaf_id: UUID | None = None
) -> list[PendingBatch]:
    """当前分支上 request 还没有对应 response 的中断批次。"""
    chat_session = await session.get(ChatSession, session_id)
    leaf = leaf_id or (chat_session.active_leaf_run_id if chat_session else None)
    if leaf is None:
        return []
    ids = await path_ids(session, session_id, leaf)
    return _pending_batches_from_path(await load_by_ids(session, ids))


async def pending_counts(session: AsyncSession, session_ids: Sequence[UUID]) -> dict[UUID, int]:
    """会话列表用的未决批次计数：按各会话当前分支统计。"""
    ids = list(session_ids)
    if not ids:
        return {}
    session_rows = (
        await session.execute(
            select(ChatSession.id, ChatSession.active_leaf_run_id).where(ChatSession.id.in_(ids))
        )
    ).all()
    run_rows = list(
        (
            await session.execute(
                select(SessionRun).where(SessionRun.session_id.in_(ids)).order_by(SessionRun.seq)
            )
        ).scalars()
    )
    by_session: dict[UUID, dict[UUID, SessionRun]] = {}
    for run in run_rows:
        by_session.setdefault(run.session_id, {})[run.id] = run
    counts: dict[UUID, int] = {}
    for session_id, leaf in session_rows:
        runs_by_id = by_session.get(session_id, {})
        path: list[SessionRun] = []
        current = leaf
        while current is not None and current in runs_by_id:
            run = runs_by_id[current]
            path.append(run)
            current = run.parent_run_id
        path.reverse()
        counts[session_id] = len(_pending_batches_from_path(path))
    return counts


async def build_context(session: AsyncSession, session_id: UUID) -> BuiltContext:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.active_leaf_run_id is None:
        return BuiltContext(runs=[], messages=[])
    path = await path_runs(session, session_id, leaf_id=chat_session.active_leaf_run_id)
    runs = path[0]
    # 未决批次就在这条路径上，别再按会话重走一遍 path_ids
    skip = {
        item.tool_call_id
        for batch in _pending_batches_from_path(runs)
        for item in batch.interrupts
    }
    messages: list[ModelMessage] = []
    # 落库的 ImageItem/VideoItem 只存 file_id；回放时把字节取回来喂模型
    media_ids = [
        item.file_id
        for run in runs
        for item in run.content
        if isinstance(item, (ImageItem, VideoItem)) and item.file_id
    ]
    media = await file_service.load_media(session, media_ids)
    for run in runs:
        messages.extend(
            item_codec.messages_from_items(run.content, usage=run.usage, media=media)
        )
    messages = item_codec.repair_dangling_tool_calls(messages, skip_tool_call_ids=skip)
    return BuiltContext(runs=runs, messages=messages)


async def usage_summary(session: AsyncSession, session_id: UUID) -> TokenUsage:
    usage = await session.scalar(select(ChatSession.usage).where(ChatSession.id == session_id))
    return usage or TokenUsage()


# ------------------------------------------------------------------ 写入


async def append_items(
    session: AsyncSession,
    session_id: UUID,
    run_id: UUID,
    items: Sequence[RunItem],
    *,
    usage: TokenUsage | None = None,
) -> SessionRun:
    if not items and (usage is None or not usage.has_values()):
        return await get_run_or_404(session, session_id, run_id)
    chat_session = await _lock(session, session_id)
    run = await _lock_run(session, session_id, run_id)
    content = [*run.content, *items]
    run.content = content
    run.preview = item_codec.preview_of(content)
    now = datetime.now(UTC)
    if usage is not None and usage.has_values():
        run.usage = run.usage.merged(usage)
        chat_session.usage = chat_session.usage.merged(usage)
    chat_session.last_run_at = now
    if chat_session.active_run_id is not None:
        chat_session.active_run_expires_at = now + timedelta(seconds=RUN_LEASE_SECONDS)
    await session.commit()
    await session.refresh(run)
    return run


async def set_run_status(
    session: AsyncSession, session_id: UUID, run_id: UUID, status: RunStatus
) -> None:
    run = await _lock_run(session, session_id, run_id)
    run.status = status.value
    await session.commit()


async def create_run(
    session: AsyncSession,
    session_id: UUID,
    *,
    run_id: UUID,
    content: Sequence[RunItem] = (),
    parent_run_id: UUID | None = None,
    status: RunStatus = RunStatus.RUNNING,
    kind: RunKind = RunKind.TURN,
    model_id: int | None = None,
    usage: TokenUsage | None = None,
    set_leaf: bool = True,
) -> SessionRun:
    chat_session = await _lock(session, session_id)
    if parent_run_id is not None:
        await get_run_or_404(session, session_id, parent_run_id)
    chat_session.run_seq += 1
    now = datetime.now(UTC)
    run = SessionRun(
        id=run_id,
        session_id=session_id,
        parent_run_id=parent_run_id,
        seq=chat_session.run_seq,
        status=status.value,
        kind=kind.value,
        content=list(content),
        model_id=model_id,
        preview=item_codec.preview_of(content),
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    if usage is not None and usage.has_values():
        run.usage = usage
        chat_session.usage = chat_session.usage.merged(usage)
    chat_session.last_run_at = now
    if set_leaf:
        chat_session.active_leaf_run_id = run.id
    await session.commit()
    await session.refresh(run)
    return run


async def start_run_turn(
    session: AsyncSession,
    session_id: UUID,
    *,
    run_id: str,
    user_input: str | None = None,
    attachments: Sequence[Attachment] = (),
    resource_items: list[RunItem] | None = None,
    retry_run_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    parent_was_given: bool = False,
    resume: ResumeDecisions | None = None,
    model_id: int | None = None,
) -> SessionRun:
    """占用当前 run；resume 先校验决定，并把叶子挪到声明批次的那条 run 上。

    决策 item 不在这里写：批次要一直算未决，直到承接它的 run 真正跑完。
    """
    chat_session = await _lock(session, session_id)
    if run_is_live(chat_session):
        await _abort(session, ConflictError(f"Session {session_id} already has an active run"))

    chat_session_id = chat_session.id
    run_uuid = UUID(run_id)
    content: list[RunItem] = []
    parent: UUID | None = None

    if resume is not None:
        parent = await _claim_resume(session, chat_session_id, chat_session, resume)
    else:
        if retry_run_id is not None:
            source = await get_run_or_404(session, session_id, retry_run_id)
            content = item_codec.copied_user_items(source.content)
            if not content:
                await _abort(
                    session, UnprocessableError(f"Run {retry_run_id} has no user input to retry")
                )
            parent = source.parent_run_id
        else:
            if user_input is None and not attachments and not resource_items:
                await _abort(session, UnprocessableError("Run has no user input"))
            if user_input is not None:
                content.extend(item_codec.user_items_from_text(user_input))
            content.extend(item_codec.attachment_items(attachments))
            content.extend(resource_items or [])
            parent = parent_run_id if parent_was_given else chat_session.active_leaf_run_id
        await _require_branch_is_quiet(session, session_id, parent)

    chat_session.run_seq += 1
    now = datetime.now(UTC)
    run = SessionRun(
        id=run_uuid,
        session_id=session_id,
        parent_run_id=parent,
        seq=chat_session.run_seq,
        status=RunStatus.RUNNING.value,
        kind=(RunKind.RESUME if resume is not None else RunKind.TURN).value,
        content=content,
        model_id=model_id,
        preview=item_codec.preview_of(content),
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()
    chat_session.active_leaf_run_id = run.id
    chat_session.last_run_at = now
    chat_session.active_run_id = run_id
    chat_session.active_run_expires_at = now + timedelta(seconds=RUN_LEASE_SECONDS)
    await session.commit()
    await session.refresh(run)
    return run


async def _require_branch_is_quiet(
    session: AsyncSession, session_id: UUID, parent: UUID | None
) -> None:
    """目标分支不能有没回填的 tool call：直接开新轮会让 provider 拒收请求。"""
    if parent is None:
        return
    # pending_batches 只沿这条分支找，有批次就一定压在目标分支上
    if await pending_batches(session, session_id, leaf_id=parent):
        await _abort(
            session,
            ConflictError(
                f"Session {session_id} has pending interrupts on this branch; resume them first"
            ),
        )


def run_is_live(chat_session: ChatSession, *, now: datetime | None = None) -> bool:
    if chat_session.active_run_id is None:
        return False
    expires_at = chat_session.active_run_expires_at
    if expires_at is None:
        return True
    # SQLite 的 DateTime(timezone=True) 读回来是 naive，按 UTC 解释才能比
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > (now or datetime.now(UTC))


async def _claim_resume(
    session: AsyncSession,
    session_id: UUID,
    chat_session: ChatSession,
    resume: ResumeDecisions,
) -> UUID:
    unresolved = await pending_batches(session, session_id)
    batch = next((item for item in unresolved if item.interrupt_id == resume.interrupt_id), None)
    if batch is None:
        await _abort(
            session,
            ConflictError(f"Interrupt batch {resume.interrupt_id} is not pending"),
        )
    known = {item.tool_call_id: item for item in batch.interrupts}
    for call_id in [*resume.approvals, *resume.calls]:
        if call_id not in known:
            await _abort(session, UnprocessableError(f"Tool call {call_id} is not pending"))
    missing = [
        item.tool_call_id
        for item in batch.interrupts
        if item.tool_call_id not in (resume.approvals if item.kind == "approval" else resume.calls)
    ]
    if missing:
        await _abort(
            session,
            UnprocessableError(
                f"Resume must cover every pending interrupt; missing {', '.join(missing)}"
            ),
        )
    # resume 的 run 从声明批次的那条 run 接着长
    chat_session.active_leaf_run_id = batch.run_id
    return batch.run_id


async def switch_leaf(
    session: AsyncSession, session_id: UUID, leaf_run_id: UUID | None
) -> ChatSession:
    """切换当前分支；被放弃的分支留在库里，只是不再进上下文。"""
    chat_session = await _lock(session, session_id)
    if run_is_live(chat_session):
        await _abort(session, ConflictError(f"Session {session_id} has an active run"))
    if leaf_run_id is not None:
        await get_run_or_404(session, session_id, leaf_run_id)
    chat_session.active_leaf_run_id = leaf_run_id
    await session.commit()
    return chat_session


async def finish_run(session: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock(session, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_id = None
        chat_session.active_run_expires_at = None
    await session.commit()


async def reserve_lease(session: AsyncSession, session_id: UUID, run_id: str) -> ChatSession:
    """非 agent run 的维护操作（如手动压缩）也占用租约，挡住并发 run。"""
    chat_session = await _lock(session, session_id)
    if run_is_live(chat_session):
        await _abort(session, ConflictError(f"Session {session_id} already has an active run"))
    now = datetime.now(UTC)
    chat_session.active_run_id = run_id
    chat_session.active_run_expires_at = now + timedelta(seconds=RUN_LEASE_SECONDS)
    await session.commit()
    return chat_session


async def renew_run_lease(session: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock(session, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_expires_at = datetime.now(UTC) + timedelta(
            seconds=RUN_LEASE_SECONDS
        )
    await session.commit()


async def clear_active_runs(session: AsyncSession) -> None:
    rows = await session.scalars(select(ChatSession).where(ChatSession.active_run_id.is_not(None)))
    expired = [chat_session.id for chat_session in rows if not run_is_live(chat_session)]
    if expired:
        await session.execute(
            update(ChatSession)
            .where(ChatSession.id.in_(expired))
            .values(active_run_id=None, active_run_expires_at=None)
        )
    await session.commit()


async def _lock(session: AsyncSession, session_id: UUID) -> ChatSession:
    chat_session = await session.scalar(
        select(ChatSession).where(ChatSession.id == session_id).with_for_update()
    )
    if chat_session is None:
        await _abort(session, NotFoundError(f"Session {session_id} not found"))
    return chat_session


async def _lock_run(session: AsyncSession, session_id: UUID, run_id: UUID) -> SessionRun:
    run = await session.scalar(
        select(SessionRun)
        .where(SessionRun.id == run_id, SessionRun.session_id == session_id)
        .with_for_update()
    )
    if run is None:
        await _abort(session, NotFoundError(f"Run {run_id} not found"))
    return run


async def _abort(session: AsyncSession, error: AppError) -> NoReturn:
    """写路径失败先回滚，别把 FOR UPDATE 的行锁留在请求会话里。"""
    await session.rollback()
    raise error
