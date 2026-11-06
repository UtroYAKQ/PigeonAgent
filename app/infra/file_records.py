"""文件记录的低层查询：storage_key 到 FileRecord 的解析。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_record import FileRecord


def is_owner_visible(owner_id: uuid.UUID | None, viewer: uuid.UUID | None) -> bool:
    """文件只对上传者本人可见；孤儿记录（owner 为空）也只有内部 owner=None 能碰。"""
    return owner_id == viewer


def _wanted_ids(keys: Sequence[uuid.UUID | str]) -> list[uuid.UUID]:
    wanted: list[uuid.UUID] = []
    for key in keys:
        try:
            wanted.append(key if isinstance(key, uuid.UUID) else uuid.UUID(str(key)))
        except ValueError:
            continue
    return wanted


async def resolve_resources(
    db: AsyncSession, keys: Sequence[uuid.UUID | str]
) -> dict[uuid.UUID, FileRecord]:
    """storage_key（=FileRecord.id）批量解析成 FileRecord；坏 key 静默跳过。

    `load_files` 工具会原样转述哪些 key 没找到，所以这里不需要抛错。
    """
    wanted = _wanted_ids(keys)
    if not wanted:
        return {}
    rows = await db.scalars(
        select(FileRecord).where(FileRecord.id.in_(wanted), FileRecord.deleted_at.is_(None))
    )
    return {row.id: row for row in rows}


async def resolve_owned_resources(
    db: AsyncSession, keys: Sequence[uuid.UUID | str], *, owner_id: uuid.UUID | None
) -> dict[uuid.UUID, FileRecord]:
    """同 ``resolve_resources``，但把归属过滤也收在这一层。

    owner_id 为 None 时只匹配孤儿记录；调用方不再自己复制 owner 判断。
    """
    wanted = _wanted_ids(keys)
    if not wanted:
        return {}
    owner_filter = (
        FileRecord.owner_id.is_(None) if owner_id is None else FileRecord.owner_id == owner_id
    )
    rows = await db.scalars(
        select(FileRecord).where(
            FileRecord.id.in_(wanted),
            FileRecord.deleted_at.is_(None),
            owner_filter,
        )
    )
    return {row.id: row for row in rows}
