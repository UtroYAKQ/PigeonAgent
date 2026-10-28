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
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.models.upload_session import UploadSession

logger = logging.getLogger(__name__)


class GcStorage(Protocol):
    async def delete(self, key: str) -> None: ...


async def sweep(
    db: AsyncSession, settings: Settings, storage: GcStorage
) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.blob_grace_seconds)
    now = datetime.now(UTC)
    await _expire_sessions(db, now, storage)
    await _purge_blobs(db, cutoff, storage)
    await db.commit()


async def _expire_sessions(db: AsyncSession, now: datetime, storage: GcStorage) -> None:
    sessions = list((await db.scalars(select(UploadSession))).all())
    expired = [
        session
        for session in sessions
        if session.expires_at.replace(tzinfo=UTC) < now
    ]
    for session in expired:
        await storage.delete(session.storage_key)
        await db.delete(session)


async def _purge_blobs(db: AsyncSession, cutoff: datetime, storage: GcStorage) -> None:
    stale = (
        select(FileRecord.id)
        .where(FileRecord.blob_hash == Blob.hash_id, FileRecord.deleted_at.is_(None))
        .exists()
    )
    candidates = await db.scalars(
        select(Blob).where(~stale, Blob.updated_at < cutoff).limit(500)
    )
    for blob in candidates:
        logger.info(
            "GC: purging blob %s (%d bytes) at %s", blob.hash_id, blob.size, blob.storage_key
        )
        await storage.delete(blob.storage_key)
        await db.delete(blob)


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
