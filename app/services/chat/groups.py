from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.chat.groups import SessionGroup
from app.models.chat.session import ChatSession
from app.schemas.chat.groups import GroupCreate

SORT_STEP = 10


async def list_groups(db: AsyncSession, *, owner_id: UUID) -> list[tuple[SessionGroup, int]]:
    """分组 + 组内会话数；一次查询拿全，侧栏不用为每组再问一次。"""
    counts = dict(
        (
            await db.execute(
                select(ChatSession.group_id, func.count())
                .where(ChatSession.owner_id == owner_id)
                .group_by(ChatSession.group_id)
            )
        ).all()
    )
    groups = await db.scalars(
        select(SessionGroup)
        .where(SessionGroup.owner_id == owner_id)
        .order_by(SessionGroup.sort_order, SessionGroup.id)
    )
    return [(group, counts.get(group.id, 0)) for group in groups]


async def session_count(db: AsyncSession, group_id: int, *, owner_id: UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(ChatSession)
        .where(ChatSession.group_id == group_id, ChatSession.owner_id == owner_id)
    )
    return count or 0


async def get_group_or_404(db: AsyncSession, group_id: int, *, owner_id: UUID) -> SessionGroup:
    group = await db.get(SessionGroup, group_id)
    if group is None or group.owner_id != owner_id:
        raise NotFoundError(f"Session group {group_id} not found")
    return group


async def _ensure_name_available(
    db: AsyncSession,
    name: str,
    *,
    owner_id: UUID,
    exclude_id: int | None = None,
) -> None:
    query = select(SessionGroup.id).where(
        SessionGroup.owner_id == owner_id, SessionGroup.name == name
    )
    if exclude_id is not None:
        query = query.where(SessionGroup.id != exclude_id)
    if await db.scalar(query) is not None:
        raise ConflictError(f"分组名称「{name}」已存在")


async def _commit_or_conflict(db: AsyncSession, name: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        # 预检查挡不住的并发重名，由唯一索引兜底
        await db.rollback()
        raise ConflictError(f"分组名称「{name}」已存在") from exc


async def create_group(db: AsyncSession, payload: GroupCreate, *, owner_id: UUID) -> SessionGroup:
    await _ensure_name_available(db, payload.name, owner_id=owner_id)
    top = await db.scalar(
        select(func.max(SessionGroup.sort_order)).where(SessionGroup.owner_id == owner_id)
    )
    group = SessionGroup(owner_id=owner_id, name=payload.name, sort_order=(top or 0) + SORT_STEP)
    db.add(group)
    await _commit_or_conflict(db, payload.name)
    await db.refresh(group)
    return group


async def rename_group(
    db: AsyncSession, group_id: int, payload: GroupCreate, *, owner_id: UUID
) -> SessionGroup:
    group = await get_group_or_404(db, group_id, owner_id=owner_id)
    await _ensure_name_available(db, payload.name, owner_id=owner_id, exclude_id=group.id)
    group.name = payload.name
    await _commit_or_conflict(db, payload.name)
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, group_id: int, *, owner_id: UUID) -> None:
    """只删组：组内会话靠外键的 SET NULL 回到未分组。"""
    group = await get_group_or_404(db, group_id, owner_id=owner_id)
    await db.delete(group)
    await db.commit()
