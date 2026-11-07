"""文件查询与删除。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.files.records import owner_filter
from app.infra.files.storage import ObjectStorage
from app.models.files.record import FileRecord
from app.schemas.file import FileRead
from app.services.file_service.content import presigned_for
from app.services.file_service.records import _blobs_of, _owned_file, _read_of, _touch_blob


async def list_files(
    db: AsyncSession, owner: uuid.UUID | None, *, limit: int = 100
) -> list[FileRead]:
    """我的文件（未软删的）；匿名调用方只匿名上传的文件，未来的接入点照此扩展。"""
    rows = list(
        await db.scalars(
            select(FileRecord)
            .where(
                owner_filter(owner),
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.created_at.desc())
            .limit(min(limit, 200))
        )
    )
    blobs = await _blobs_of(db, [row.blob_hash for row in rows])
    return [_read_of(row, blobs.get(row.blob_hash)) for row in rows]


async def visit(
    db: AsyncSession,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    file_id: uuid.UUID,
) -> str:
    """归属校验通过就签一条短时效 URL；307 由端点负责。"""
    file = await _owned_file(db, owner, file_id)
    return await presigned_for(db, storage, file, inline=False)


async def soft_delete(db: AsyncSession, owner: uuid.UUID | None, file_id: uuid.UUID) -> None:
    file = await _owned_file(db, owner, file_id)
    if file.deleted_at is None:
        file.deleted_at = datetime.now(UTC)
        # 宽限锚点跟着动：最后一次动这个 blob 的引用时间才作数
        await _touch_blob(db, file.blob_hash)
        await db.commit()
