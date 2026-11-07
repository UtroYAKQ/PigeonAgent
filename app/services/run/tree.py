"""run 树读取：路径、分页、分支导航。"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased as orm_aliased

from app.core.exceptions import NotFoundError
from app.models.session import ChatSession
from app.models.session_run import SessionRun
from app.schemas.run import BranchNav


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


def invalidate_branch_cache(session_id: UUID) -> None:
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
    if not runs:
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
            select(SessionRun.id, SessionRun.parent_run_id, SessionRun.seq)
            .where(SessionRun.session_id == session_id)
            .order_by(SessionRun.seq)
        )
    ).all()
    children: defaultdict[UUID | None, list[UUID]] = defaultdict(list)
    for row in rows:
        children[row.parent_run_id].append(row.id)

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
        siblings = children.get(row.parent_run_id, [])
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
        raise NotFoundError(f"轮次 {run_id} 不存在")
    return run
