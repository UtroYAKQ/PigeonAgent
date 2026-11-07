"""文件记录与物理块的共享查询/绑定。"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.domain.media_type import effective_media_type
from app.infra.file_records import is_owner_visible
from app.infra.storage import safe_name
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.models.upload_session import UploadSession
from app.schemas.file import FileRead


def _hash_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blob_key() -> str:
    return f"blobs/{uuid.uuid4().hex}"


def _read_of(row: FileRecord, blob: Blob | None) -> FileRead:
    return FileRead(
        id=row.id,
        name=row.name,
        size=blob.size if blob is not None else 0,
        content_type=effective_media_type(row.name, row.content_type),
        sha256=row.blob_hash,
    )


async def _blobs_of(db: AsyncSession, hashes: Sequence[str]) -> dict[str, Blob]:
    """按 hash 批量取物理块：列表和回放都一次拿齐，别逐行 db.get。"""
    wanted = list(dict.fromkeys(hashes))
    if not wanted:
        return {}
    rows = await db.scalars(select(Blob).where(Blob.hash_id.in_(wanted)))
    return {row.hash_id: row for row in rows}


def _file_for(
    owner: uuid.UUID | None, name: str | None, sha256: str, content_type: str | None
) -> FileRecord:
    safe = safe_name(name)
    return FileRecord(
        owner_id=owner,
        name=safe,
        blob_hash=sha256,
        content_type=effective_media_type(safe, content_type),
    )


async def _touch_blob(db: AsyncSession, blob_hash: str) -> None:
    """挂新引用时推一把宽限锚点，免得 GC 恰好扫到刚复活的 blob。"""
    await db.execute(
        update(Blob).where(Blob.hash_id == blob_hash).values(updated_at=datetime.now(UTC))
    )


async def _bind_blob(db: AsyncSession, *, sha256: str, size: int, storage_key: str) -> Blob:
    """同 hash 并发竞争时只有一行能进来；输家拿现成的那一行。"""
    blob = Blob(hash_id=sha256, size=size, storage_key=storage_key)
    db.add(blob)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        winner = await db.get(Blob, sha256)
        if winner is None:
            raise
        return winner
    return blob


async def _owned_session(
    db: AsyncSession, owner: uuid.UUID | None, upload_id: uuid.UUID
) -> UploadSession:
    session = await db.get(UploadSession, upload_id)
    # 归属不符同样 404：不把别人会话的存在性泄露出来
    if session is None or not is_owner_visible(session.owner_id, owner):
        raise NotFoundError("上传会话不存在或已失效")
    return session


async def _owned_file(db: AsyncSession, owner: uuid.UUID | None, file_id: uuid.UUID) -> FileRecord:
    file = await db.get(FileRecord, file_id)
    if file is None or not is_owner_visible(file.owner_id, owner) or file.deleted_at is not None:
        raise NotFoundError("文件不存在")
    return file
