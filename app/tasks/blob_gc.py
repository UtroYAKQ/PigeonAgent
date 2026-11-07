"""blob GC 巡检：引用归零的物理块、过期的上传会话。

宽限锚点是 blobs.updated_at：file_service 在建/删引用时都会推它，
所以秒传/直传复活的 blob 一定不会被当轮巡检误删。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.files.blob import Blob
from app.models.files.record import FileRecord
from app.models.files.upload import UploadSession

logger = logging.getLogger(__name__)


class GcStorage(Protocol):
    async def delete(self, key: str) -> None: ...


async def sweep(db: AsyncSession, settings: Settings, storage: GcStorage) -> None:
    """先删库并提交，再删对象存储。

    反过来做（先删对象）一旦 commit 失败，库里留着行、字节已经没了：
    秒传会把用户指向一个不存在的文件。宁可漏删对象——下面会把 key 记出来。
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.blob_grace_seconds)
    now = datetime.now(UTC)
    orphan_keys = await _expire_sessions(db, now)
    orphan_keys += await _purge_blobs(db, cutoff)
    await db.commit()
    await _delete_objects(storage, orphan_keys)


async def _expire_sessions(db: AsyncSession, now: datetime) -> list[str]:
    """清掉过期的 presign 上传会话，返回它们占着的对象 key。"""
    # 只取已过期的会话，别把整张上传会话表读进内存
    expired = list(
        (await db.scalars(select(UploadSession).where(UploadSession.expires_at < now))).all()
    )
    keys: list[str] = []
    for upload in expired:
        keys.append(upload.storage_key)
        await db.delete(upload)
    return keys


async def _purge_blobs(db: AsyncSession, cutoff: datetime) -> list[str]:
    stale = (
        select(FileRecord.id)
        .where(FileRecord.blob_hash == Blob.hash_id, FileRecord.deleted_at.is_(None))
        .exists()
    )
    candidates = await db.scalars(select(Blob).where(~stale, Blob.updated_at < cutoff).limit(500))
    keys: list[str] = []
    for blob in candidates:
        logger.info(
            "GC: purging blob %s (%d bytes) at %s", blob.hash_id, blob.size, blob.storage_key
        )
        keys.append(blob.storage_key)
        await db.delete(blob)
    return keys


async def _delete_objects(storage: GcStorage, keys: list[str]) -> None:
    """删除失败只是桶里多留一块没人引用的字节，不影响任何可读文件。"""
    for key in keys:
        try:
            await storage.delete(key)
        except Exception:
            logger.exception(
                "GC: %s stays in storage without a database row; needs a manual sweep", key
            )


async def run_forever(
    factory: async_sessionmaker[AsyncSession], settings: Settings, storage: GcStorage
) -> None:
    interval = settings.gc_interval_seconds
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            async with factory() as session:
                await sweep(session, settings, storage)
        except Exception:
            logger.exception("Blob GC sweep failed; will retry next interval")
