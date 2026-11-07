"""媒体回放：进程内缓存、并行取字节和删除后的语义。"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.schemas.file import FileRead
from app.services import file_service
from tests.test_files import FakeStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"cache"


class _CountingStorage(FakeStorage):
    def __init__(self) -> None:
        super().__init__()
        self.gets = 0
        self.active = 0
        self.peak = 0

    async def get(self, key: str) -> bytes:
        self.gets += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().get(key)
        finally:
            self.active -= 1


async def _seed(db: AsyncSession, storage: FakeStorage, name: str = "pic.png") -> FileRead:
    settings = Settings(secret_key="x" * 44)
    return await file_service.direct_upload(db, settings, storage, None, name, "image/png", PNG)


async def test_load_media_reuses_cached_bytes(db_session: AsyncSession) -> None:
    storage = _CountingStorage()
    record = await _seed(db_session, storage)

    first = await file_service.load_media(db_session, [str(record.id)], storage=storage)
    second = await file_service.load_media(db_session, [str(record.id)], storage=storage)

    assert first[str(record.id)] == PNG
    assert second[str(record.id)] == PNG
    assert storage.gets == 1


async def test_load_media_fetches_in_parallel(db_session: AsyncSession) -> None:
    storage = _CountingStorage()
    records = [await _seed(db_session, storage, f"pic-{index}.png") for index in range(6)]

    loaded = await file_service.load_media(
        db_session, [str(record.id) for record in records], storage=storage
    )

    assert len(loaded) == 6
    assert storage.peak > 1


async def test_load_media_does_not_serve_soft_deleted_files(
    db_session: AsyncSession,
) -> None:
    storage = _CountingStorage()
    record = await _seed(db_session, storage)
    await file_service.load_media(db_session, [str(record.id)], storage=storage)
    await file_service.soft_delete(db_session, None, record.id)

    assert await file_service.load_media(db_session, [str(record.id)], storage=storage) == {}
    assert storage.gets == 1
