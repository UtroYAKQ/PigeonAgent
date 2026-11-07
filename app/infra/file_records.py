"""文件记录的低层查询：file_id 到 FileRecord 的解析。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.ids import parse_uuid
from app.models.file_record import FileRecord


def is_owner_visible(owner_id: uuid.UUID | None, viewer: uuid.UUID | None) -> bool:
    """文件只对上传者本人可见；孤儿记录（owner 为空）也只有内部 owner=None 能碰。"""
    return owner_id == viewer


def owner_filter(owner_id: uuid.UUID | None) -> ColumnElement[bool]:
    """归属谓词的 SQL 形状；owner_id 为 None 时只匹配孤儿记录。"""
    return FileRecord.owner_id.is_(None) if owner_id is None else FileRecord.owner_id == owner_id


def _wanted_ids(file_ids: Sequence[uuid.UUID | str]) -> list[uuid.UUID]:
    return [parsed for file_id in file_ids if (parsed := parse_uuid(file_id)) is not None]


async def resolve_files(
    db: AsyncSession, file_ids: Sequence[uuid.UUID | str]
) -> dict[uuid.UUID, FileRecord]:
    """file_id 批量解析成 FileRecord；坏 id 静默跳过。

    `load_files` 工具会原样转述哪些 id 没找到，所以这里不需要抛错。
    """
    wanted = _wanted_ids(file_ids)
    if not wanted:
        return {}
    rows = await db.scalars(
        select(FileRecord).where(FileRecord.id.in_(wanted), FileRecord.deleted_at.is_(None))
    )
    return {row.id: row for row in rows}


async def resolve_owned_files(
    db: AsyncSession, file_ids: Sequence[uuid.UUID | str], *, owner_id: uuid.UUID | None
) -> dict[uuid.UUID, FileRecord]:
    """同 ``resolve_files``，但把归属过滤也收在这一层。

    调用方不再自己复制 owner 判断。
    """
    wanted = _wanted_ids(file_ids)
    if not wanted:
        return {}
    rows = await db.scalars(
        select(FileRecord).where(
            FileRecord.id.in_(wanted),
            FileRecord.deleted_at.is_(None),
            owner_filter(owner_id),
        )
    )
    return {row.id: row for row in rows}
