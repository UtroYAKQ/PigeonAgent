"""run 树的写入、上下文拼接、中断与压缩窗口。

run 用 parent_run_id 组树，`sessions.active_leaf_run_id` 指向当前分支末端。
当前分支就是从叶子往根的那条链，所以上下文、分页和重新生成都按路径走。
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from sqlalchemy import func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased as orm_aliased

from app import codec
from app.core.exceptions import AppError, ConflictError, NotFoundError, UnprocessableError
from app.domain.run_items import (
    ApprovalRequestItem,
    CallRequestItem,
    CompactionItem,
    ImageItem,
    PendingInterrupt,
    PendingInterrupts,
    RunItem,
    TokenUsage,
    ToolResultItem,
    VideoItem,
)
from app.enums import RunKind, RunStatus
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run import Attachment, BranchNav
from app.services import file_service

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
    pending: list[PendingBatch] = field(default_factory=list)


# ------------------------------------------------------------------ 读取


async def path_ids(db: AsyncSession, session_id: UUID, leaf_id: UUID) -> list[UUID]:
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
    depth_cap = await db.scalar(
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
    rows = await db.execute(select(path.c.id, path.c.depth).order_by(path.c.depth.desc()))
    return [row[0] for row in rows]


async def load_by_ids(db: AsyncSession, ids: Sequence[UUID]) -> list[SessionRun]:
    if not ids:
        return []
    rows = await db.scalars(select(SessionRun).where(SessionRun.id.in_(list(ids))))
    by_id = {row.id: row for row in rows}
    return [by_id[item] for item in ids if item in by_id]


_BRANCH_CACHE_LIMIT = 128
_branch_cache: OrderedDict[UUID, tuple[tuple[int, UUID | None], dict[UUID, BranchNav]]] = (
    OrderedDict()
)


def _invalidate_branch_cache(session_id: UUID) -> None:
    """写路径改了 run 树拓扑后立刻作废缓存，读侧不用再猜。"""
    _branch_cache.pop(session_id, None)


async def branch_navs(
    db: AsyncSession,
    session_id: UUID,
    runs: Sequence[SessionRun],
    *,
    chat_session: ChatSession | None = None,
) -> dict[UUID, BranchNav]:
    """给当前页的 turn run 算分支版本和各自的末端。

    分支拓扑只在新建 run / 切换叶子时变化，用小 LRU 按
    (run_seq, active_leaf_run_id) 缓存整张导航表；翻页和重复请求不再扫全树。
    """
    if not any(run.kind == RunKind.TURN.value for run in runs):
        return {}
    if chat_session is None:
        chat_session = await db.get(ChatSession, session_id)
    if chat_session is None:
        return {}
    cache_key = (chat_session.run_seq, chat_session.active_leaf_run_id)
    cached = _branch_cache.get(session_id)
    if cached is not None and cached[0] == cache_key:
        _branch_cache.move_to_end(session_id)
        return {run.id: cached[1][run.id] for run in runs if run.id in cached[1]}

    rows = (
        await db.execute(
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
    for row in rows:
        if row.kind != RunKind.TURN.value:
            continue
        siblings = [
            run_id
            for run_id in children.get(row.parent_run_id, [])
            if kinds[run_id] == RunKind.TURN.value
        ]
        if len(siblings) < 2:
            continue
        navs[row.id] = BranchNav(
            position=siblings.index(row.id) + 1,
            total=len(siblings),
            leaves=[tip(run_id) for run_id in siblings],
        )
    _branch_cache[session_id] = (cache_key, navs)
    _branch_cache.move_to_end(session_id)
    if len(_branch_cache) > _BRANCH_CACHE_LIMIT:
        _branch_cache.popitem(last=False)
    return {run.id: navs[run.id] for run in runs if run.id in navs}


async def path_runs(
    db: AsyncSession,
    session_id: UUID,
    *,
    leaf_id: UUID | None = None,
    limit: int | None = None,
    before_run_id: UUID | None = None,
) -> tuple[list[SessionRun], bool]:
    """当前分支的 run（根→叶）。返回 (这一页, 更早的还有没有)。"""
    chat_session = await db.get(ChatSession, session_id)
    leaf_id = leaf_id or (chat_session.active_leaf_run_id if chat_session else None)
    if leaf_id is None:
        return [], False
    ids = await path_ids(db, session_id, leaf_id)
    if before_run_id is not None and before_run_id in ids:
        ids = ids[: ids.index(before_run_id)]
    has_more = limit is not None and len(ids) > limit
    if limit is not None:
        ids = ids[-limit:]
    return await load_by_ids(db, ids), has_more


async def get_run_or_404(db: AsyncSession, session_id: UUID, run_id: UUID) -> SessionRun:
    run = await db.scalar(
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
    return _pending_batches_from_path(await load_by_ids(db, ids))


async def _sync_pending_count(
    db: AsyncSession,
    chat_session: ChatSession,
    leaf: UUID | None,
) -> None:
    """按目标分支重算计数；调用方负责事务提交。"""
    batches = await _pending_for_leaf(db, chat_session.id, leaf)
    chat_session.pending_batches = len(batches)


def _compaction_start(runs: Sequence[SessionRun]) -> tuple[int, int] | None:
    """自底向上找最近的压缩节点，返回 (run 下标, 该 run 内最后一个压缩 Item 下标)。"""
    for run_index in range(len(runs) - 1, -1, -1):
        run = runs[run_index]
        if not run.compacted:
            continue
        for item_index in range(len(run.content) - 1, -1, -1):
            if isinstance(run.content[item_index], CompactionItem):
                return run_index, item_index
        # 标记在但 Item 丢了：保守地从这一 run 的开头算起，宁可多带不可漏带
        return run_index, 0
    return None


async def build_context(
    db: AsyncSession, session_id: UUID, *, leaf_id: UUID | None = None
) -> BuiltContext:
    chat_session = await db.get(ChatSession, session_id)
    leaf = (
        leaf_id
        if leaf_id is not None
        else (chat_session.active_leaf_run_id if chat_session is not None else None)
    )
    if leaf is None:
        return BuiltContext(runs=[], messages=[])
    path = await path_runs(db, session_id, leaf_id=leaf)
    runs = path[0]
    first_items: Sequence[RunItem] | None = None
    start = _compaction_start(runs)
    if start is not None:
        run_index, item_index = start
        runs = runs[run_index:]
        first_items = runs[0].content[item_index:]
    # 未决批次就在这条路径上，别再按会话重走一遍 path_ids
    pending = _pending_batches_from_path(runs)
    skip = {item.tool_call_id for batch in pending for item in batch.interrupts}
    messages: list[ModelMessage] = []
    slices = [
        (run, first_items if index == 0 and first_items is not None else run.content)
        for index, run in enumerate(runs)
    ]
    # 落库的 ImageItem/VideoItem 只存 file_id；回放时把字节取回来喂模型
    media_ids = [
        item.file_id
        for _, items in slices
        for item in items
        if isinstance(item, (ImageItem, VideoItem)) and item.file_id
    ]
    media = await file_service.load_media(db, media_ids)
    for run, items in slices:
        messages.extend(codec.messages_from_items(items, usage=run.usage, media=media))
    messages = codec.repair_dangling_tool_calls(messages, skip_tool_call_ids=skip)
    return BuiltContext(runs=runs, messages=messages, pending=pending)


# ------------------------------------------------------------------ 写入


def _lease_expires_at(now: datetime) -> datetime:
    """租约到期时刻；占用、被动续租和显式 renew 都从这里算，租约时长只解释一次。"""
    return now + timedelta(seconds=RUN_LEASE_SECONDS)


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
        chat_session.active_run_expires_at = _lease_expires_at(now)


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
        await _sync_pending_count(db, chat_session, chat_session.active_leaf_run_id)
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
    kind: RunKind = RunKind.TURN,
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
        kind=kind.value,
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
        await _sync_pending_count(db, chat_session, run.id)
    await db.commit()
    await db.refresh(run)
    _invalidate_branch_cache(session_id)
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
    parent_was_given: bool = False,
    resume: ResumeDecisions | None = None,
    model_id: int | None = None,
) -> SessionRun:
    """占用当前 run；resume 先校验决定，并把叶子挪到声明批次的那条 run 上。

    决策 item 不在这里写：批次要一直算未决，直到承接它的 run 真正跑完。
    """
    chat_session = await _lock(db, session_id)
    if run_is_live(chat_session):
        await _abort(
            db,
            ConflictError(
                f"Session {session_id} already has an active run",
                active_run_id=chat_session.active_run_id,
            ),
        )

    chat_session_id = chat_session.id
    run_uuid = UUID(run_id)
    content: list[RunItem] = []
    parent: UUID | None = None

    if resume is not None:
        parent = await _claim_resume(db, chat_session_id, chat_session, resume)
    else:
        if retry_run_id is not None:
            source = await get_run_or_404(db, session_id, retry_run_id)
            content = codec.copied_user_items(source.content)
            if not content:
                await _abort(
                    db, UnprocessableError(f"Run {retry_run_id} has no user input to retry")
                )
            parent = source.parent_run_id
        else:
            if user_input is None and not attachments and not resource_items:
                await _abort(db, UnprocessableError("Run has no user input"))
            if user_input is not None:
                content.extend(codec.user_items_from_text(user_input))
            content.extend(codec.attachment_items(attachments))
            content.extend(resource_items or [])
            parent = parent_run_id if parent_was_given else chat_session.active_leaf_run_id
        await _require_branch_is_quiet(db, session_id, parent)

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
    chat_session.active_run_expires_at = _lease_expires_at(now)
    if resume is None:
        # 新轮只在 quiet 分支上开，未决批次必为 0，不用为此扫整条路径
        chat_session.pending_batches = 0
    else:
        await _sync_pending_count(db, chat_session, run.id)
    await db.commit()
    await db.refresh(run)
    _invalidate_branch_cache(session_id)
    return run


async def _require_branch_is_quiet(db: AsyncSession, session_id: UUID, parent: UUID | None) -> None:
    """目标分支不能有没回填的 tool call：直接开新轮会让 provider 拒收请求。"""
    if parent is None:
        return
    # pending_batches 只沿这条分支找，有批次就一定压在目标分支上
    if await pending_batches(db, session_id, leaf_id=parent):
        await _abort(
            db,
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
    db: AsyncSession,
    session_id: UUID,
    chat_session: ChatSession,
    resume: ResumeDecisions,
) -> UUID:
    unresolved = await pending_batches(db, session_id)
    batch = next((item for item in unresolved if item.interrupt_id == resume.interrupt_id), None)
    if batch is None:
        await _abort(
            db,
            ConflictError(f"Interrupt batch {resume.interrupt_id} is not pending"),
        )
    known = {item.tool_call_id: item for item in batch.interrupts}
    for call_id in [*resume.approvals, *resume.calls]:
        if call_id not in known:
            await _abort(db, UnprocessableError(f"Tool call {call_id} is not pending"))
    missing = [
        item.tool_call_id
        for item in batch.interrupts
        if item.tool_call_id not in (resume.approvals if item.kind == "approval" else resume.calls)
    ]
    if missing:
        await _abort(
            db,
            UnprocessableError(
                f"Resume must cover every pending interrupt; missing {', '.join(missing)}"
            ),
        )
    # resume 的 run 从声明批次的那条 run 接着长
    chat_session.active_leaf_run_id = batch.run_id
    return batch.run_id


async def switch_leaf(db: AsyncSession, session_id: UUID, leaf_run_id: UUID | None) -> ChatSession:
    """切换当前分支；被放弃的分支留在库里，只是不再进上下文。"""
    chat_session = await _lock(db, session_id)
    if run_is_live(chat_session):
        await _abort(db, ConflictError(f"Session {session_id} has an active run"))
    if leaf_run_id is not None:
        await get_run_or_404(db, session_id, leaf_run_id)
    chat_session.active_leaf_run_id = leaf_run_id
    await _sync_pending_count(db, chat_session, leaf_run_id)
    await db.commit()
    _invalidate_branch_cache(session_id)
    return chat_session


async def finish_run(db: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock(db, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_id = None
        chat_session.active_run_expires_at = None
    await db.commit()


async def renew_run_lease(db: AsyncSession, session_id: UUID, run_id: str) -> None:
    chat_session = await _lock(db, session_id)
    if chat_session.active_run_id == run_id:
        chat_session.active_run_expires_at = _lease_expires_at(datetime.now(UTC))
    await db.commit()


async def clear_expired_run_leases(db: AsyncSession) -> None:
    """启动清扫：只回收已过期的租约，活着的跨进程 run 不受影响。"""
    rows = await db.scalars(select(ChatSession).where(ChatSession.active_run_id.is_not(None)))
    expired = [chat_session.id for chat_session in rows if not run_is_live(chat_session)]
    if expired:
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id.in_(expired))
            .values(active_run_id=None, active_run_expires_at=None)
        )
    await db.commit()


async def _lock(db: AsyncSession, session_id: UUID) -> ChatSession:
    chat_session = await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id).with_for_update()
    )
    if chat_session is None:
        await _abort(db, NotFoundError(f"Session {session_id} not found"))
    return chat_session


async def _lock_run(db: AsyncSession, session_id: UUID, run_id: UUID) -> SessionRun:
    run = await db.scalar(
        select(SessionRun)
        .where(SessionRun.id == run_id, SessionRun.session_id == session_id)
        .with_for_update()
    )
    if run is None:
        await _abort(db, NotFoundError(f"Run {run_id} not found"))
    return run


async def _abort(db: AsyncSession, error: AppError) -> NoReturn:
    """写路径失败先回滚，别把 FOR UPDATE 的行锁留在请求会话里。"""
    await db.rollback()
    raise error
