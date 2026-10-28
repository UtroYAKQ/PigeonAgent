from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.session import ChatSession
from app.models.session_group import SessionGroup
from app.schemas.session_group import GroupCreate

SORT_STEP = 10


async def list_groups(
    session: AsyncSession, *, owner_id: UUID
) -> list[tuple[SessionGroup, int]]:
    """分组 + 组内会话数；一次查询拿全，侧栏不用为每组再问一次。"""
    counts = dict(
        (
            await session.execute(
                select(ChatSession.group_id, func.count())
                .where(ChatSession.owner_id == owner_id)
                .group_by(ChatSession.group_id)
            )
        ).all()
    )
    groups = await session.scalars(
        select(SessionGroup)
        .where(SessionGroup.owner_id == owner_id)
        .order_by(SessionGroup.sort_order, SessionGroup.id)
    )
    return [(group, counts.get(group.id, 0)) for group in groups]


async def session_count(session: AsyncSession, group_id: int, *, owner_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(ChatSession)
        .where(ChatSession.group_id == group_id, ChatSession.owner_id == owner_id)
    )
    return count or 0


async def get_group_or_404(
    session: AsyncSession, group_id: int, *, owner_id: UUID
) -> SessionGroup:
    group = await session.get(SessionGroup, group_id)
    if group is None or group.owner_id != owner_id:
        raise NotFoundError(f"Session group {group_id} not found")
    return group


async def create_group(
    session: AsyncSession, payload: GroupCreate, *, owner_id: UUID
) -> SessionGroup:
    top = await session.scalar(
        select(func.max(SessionGroup.sort_order)).where(SessionGroup.owner_id == owner_id)
    )
    group = SessionGroup(
        owner_id=owner_id, name=payload.name, sort_order=(top or 0) + SORT_STEP
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def rename_group(
    session: AsyncSession, group_id: int, payload: GroupCreate, *, owner_id: UUID
) -> SessionGroup:
    group = await get_group_or_404(session, group_id, owner_id=owner_id)
    group.name = payload.name
    await session.commit()
    await session.refresh(group)
    return group


async def delete_group(session: AsyncSession, group_id: int, *, owner_id: UUID) -> None:
    """只删组：组内会话靠外键的 SET NULL 回到未分组。"""
    group = await get_group_or_404(session, group_id, owner_id=owner_id)
    await session.delete(group)
    await session.commit()
