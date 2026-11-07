"""上传：秒传探测、小文件直传与分片上传收尾。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import GoneError, UnprocessableError
from app.domain.media_type import effective_media_type
from app.domain.time import ensure_utc
from app.infra.file_records import owner_filter
from app.infra.storage import ObjectStorage, safe_name, upload_key
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.models.upload_session import UploadSession
from app.schemas.file import FilePrepare, FilePrepareOut, FileRead
from app.services.file_service.records import (
    _bind_blob,
    _blob_key,
    _file_for,
    _hash_hex,
    _owned_session,
    _read_of,
    _touch_blob,
)


async def instant_create(
    db: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    payload: FilePrepare,
) -> FilePrepareOut:
    """本人已有同内容文件时秒传；否则必须上传并由服务端复核内容。"""
    blob = await db.get(Blob, payload.sha256)
    owned_reference = await db.scalar(
        select(FileRecord.id).where(
            owner_filter(owner),
            FileRecord.blob_hash == payload.sha256,
            FileRecord.deleted_at.is_(None),
        )
    )
    if blob is not None and owned_reference is not None:
        file = await _add_reference(
            db, owner, payload.name, payload.sha256, payload.content_type, blob
        )
        return FilePrepareOut(deduplicated=True, file=file)
    return await _presign_upload(db, settings, storage, owner, payload)


async def _presign_upload(
    db: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    payload: FilePrepare,
) -> FilePrepareOut:
    """登一个上传会话，给客户端直达上传区的 PUT 签名。"""
    session = UploadSession(
        owner_id=owner,
        name=safe_name(payload.name),
        declared_sha256=payload.sha256,
        declared_size=payload.size,
        content_type=payload.content_type,
        storage_key=upload_key(settings.s3_prefix),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.upload_session_ttl_seconds),
    )
    db.add(session)
    await db.commit()
    return FilePrepareOut(
        deduplicated=False,
        upload_id=session.id,
        upload_url=await storage.presign_put(
            session.storage_key, content_length=session.declared_size
        ),
        expires_in=settings.s3_presign_ttl_seconds,
    )


async def complete_upload(
    db: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    upload_id: uuid.UUID,
) -> FileRead:
    """客户端 PUT 完调用：复核内容指纹，搬运到正式 key，建物理块和引用。"""
    session = await _owned_session(db, owner, upload_id)
    if ensure_utc(session.expires_at) < datetime.now(UTC):
        # 会话过期就整条丢弃：对象留着只会变成无人引用的垃圾
        await storage.delete(session.storage_key)
        await db.delete(session)
        await db.commit()
        raise GoneError("上传会话已过期，请重新发起")

    head = await storage.head(session.storage_key)
    if head is None:
        raise UnprocessableError("对象还没传上去，先完成 PUT 再 complete")
    if head.size != session.declared_size:
        raise UnprocessableError(f"文件大小不符：声明 {session.declared_size}，实际 {head.size}")

    actual = _hash_hex(await storage.get(session.storage_key))
    if actual != session.declared_sha256:
        # 指纹对不上说明客户端算错或传坏，内容不可信
        await storage.delete(session.storage_key)
        await db.delete(session)
        await db.commit()
        raise UnprocessableError("文件内容与声明指纹不符，已丢弃这次上传")

    return await _finalize(db, storage, session, actual, head.size)


async def _finalize(
    db: AsyncSession,
    storage: ObjectStorage,
    session: UploadSession,
    sha256: str,
    size: int,
) -> FileRead:
    # _bind_blob 竞态失败时会 rollback，session 随之过期；先把要用的字段读出来
    owner_id = session.owner_id
    name = session.name
    content_type = session.content_type
    blob = await db.get(Blob, sha256)
    if blob is None:
        target = _blob_key()
        await storage.copy(session.storage_key, target)
        blob = await _bind_blob(db, sha256=sha256, size=size, storage_key=target)
        if blob.storage_key != target:
            # 并发同内容输掉了 _bind_blob 竞态：刚 copy 出来的那份成了孤儿，立刻清掉
            await storage.delete(target)
    await storage.delete(session.storage_key)
    await db.delete(session)
    return await _add_reference(db, owner_id, name, sha256, content_type, blob)


async def direct_upload(
    db: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    name: str | None,
    content_type: str | None,
    body: bytes,
) -> FileRead:
    """小文件直传：服务端亲算 hash，先对齐物理层再建逻辑引用。"""
    content_type = effective_media_type(name, content_type, body)
    sha256 = _hash_hex(body)
    blob = await db.get(Blob, sha256)
    if blob is None:
        # put 在 blob 建行之前：万一并发同内容输掉，多方多出的那份对象要清掉
        result = await storage.put(_blob_key(), body, content_type)
        blob = await _bind_blob(db, sha256=sha256, size=result.size, storage_key=result.key)
        if blob.storage_key != result.key:
            await storage.delete(result.key)
    return await _add_reference(db, owner, name, sha256, content_type, blob)


async def _add_reference(
    db: AsyncSession,
    owner: uuid.UUID | None,
    name: str | None,
    sha256: str,
    content_type: str | None,
    blob: Blob,
) -> FileRead:
    """物理块已就位后建逻辑引用：三种上传路径共用这一处。"""
    file = _file_for(owner, name, sha256, content_type)
    db.add(file)
    await _touch_blob(db, sha256)
    await db.commit()
    return _read_of(file, blob)
