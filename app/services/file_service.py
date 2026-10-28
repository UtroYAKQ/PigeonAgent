"""文件服务：物理块去重 + 逻辑文件引用 + 短时效签名 URL。

物理层（blobs）只认内容：hash 即身份，桶里同样的内容只存一份。
逻辑层（files）只承载业务：owner、原始文件名、指向的 hash。
上层关心的三件事——秒传、临时 URL、引用归零后等 GC 收物理块。
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings
from app.core.exceptions import (
    GoneError,
    NotFoundError,
    StorageUnavailableError,
    UnprocessableError,
)
from app.models.blob import Blob
from app.models.file_record import FileRecord
from app.models.upload_session import UploadSession
from app.schemas.file import FilePrepare, FilePrepareOut, FileRead
from app.schemas.run import Attachment, ResourceRef
from app.schemas.run_item import ImageItem, ResourceItem, RunItem, VideoItem
from app.services.storage import ObjectStorage, get_storage, safe_name, upload_key


def _matches_owner(owner_id: uuid.UUID | None, user: uuid.UUID | None) -> bool:
    """匿名上传（owner 为 null）对所有调用方可见；实名上传只对本人可见。"""
    return owner_id is None or owner_id == user


def _hash_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blob_key() -> str:
    return f"blobs/{uuid.uuid4().hex}"


def _read_of(row: FileRecord, blob: Blob | None) -> FileRead:
    return FileRead(
        id=row.id,
        name=row.name,
        size=blob.size if blob is not None else 0,
        content_type=row.content_type,
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
    return FileRecord(
        owner_id=owner,
        name=safe_name(name),
        blob_hash=sha256,
        content_type=content_type,
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


async def instant_create(
    db: AsyncSession,
    settings: Settings,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    payload: FilePrepare,
) -> FilePrepareOut:
    """hash 命中秒传：0 字节传输，直接建逻辑引用；未命中走 presign 上传。"""
    blob = await db.get(Blob, payload.sha256)
    if blob is not None:
        file = _file_for(owner, payload.name, payload.sha256, payload.content_type)
        db.add(file)
        await _touch_blob(db, payload.sha256)
        await db.commit()
        return FilePrepareOut(deduplicated=True, file=_read_of(file, blob))
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
        upload_url=await storage.presign_put(session.storage_key),
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
    if session.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        await db.delete(session)
        await db.commit()
        raise GoneError("上传会话已过期，请重新发起")

    head = await storage.head(session.storage_key)
    if head is None:
        raise UnprocessableError("对象还没传上去，先完成 PUT 再 complete")
    if head.size != session.declared_size:
        raise UnprocessableError(
            f"文件大小不符：声明 {session.declared_size}，实际 {head.size}"
        )

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
    blob = await db.get(Blob, sha256)
    if blob is None:
        target = _blob_key()
        await storage.copy(session.storage_key, target)
        blob = await _bind_blob(db, sha256=sha256, size=size, storage_key=target)
    await storage.delete(session.storage_key)
    await db.delete(session)
    file = FileRecord(
        owner_id=session.owner_id,
        name=session.name,
        blob_hash=sha256,
        content_type=session.content_type,
    )
    db.add(file)
    await _touch_blob(db, sha256)
    await db.commit()
    return _read_of(file, blob)


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
    sha256 = _hash_hex(body)
    blob = await db.get(Blob, sha256)
    if blob is None:
        # put 在 blob 建行之前：万一并发同内容输掉，多方多出的那份对象要清掉
        result = await storage.put(_blob_key(), body, content_type)
        blob = await _bind_blob(db, sha256=sha256, size=result.size, storage_key=result.key)
        if blob.storage_key != result.key:
            await storage.delete(result.key)
    file = _file_for(owner, name, sha256, content_type)
    db.add(file)
    await _touch_blob(db, sha256)
    await db.commit()
    return _read_of(file, blob)


async def list_files(
    db: AsyncSession, owner: uuid.UUID | None, *, limit: int = 100
) -> list[FileRead]:
    """我的文件（未软删的）；匿名调用方只匿名上传的文件，未来的接入点照此扩展。"""
    rows = list(
        await db.scalars(
            select(FileRecord)
            .where(
                _record_owner_visible(owner),
                FileRecord.deleted_at.is_(None),
            )
            .order_by(FileRecord.created_at.desc())
            .limit(min(limit, 200))
        )
    )
    blobs = await _blobs_of(db, [row.blob_hash for row in rows])
    return [_read_of(row, blobs.get(row.blob_hash)) for row in rows]


def _record_owner_visible(user: uuid.UUID | None) -> ColumnElement[bool]:
    return FileRecord.owner_id.is_(None) if user is None else FileRecord.owner_id == user


async def resolve_resources(
    db: AsyncSession, keys: Sequence[uuid.UUID | str]
) -> dict[uuid.UUID, FileRecord]:
    """storage_key（=FileRecord.id）批量解析成 FileRecord；坏 key 静默跳过。

    `load_files` 工具会原样转述哪些 key 没找到，所以这里不需要抛错。
    """
    wanted: list[uuid.UUID] = []
    for key in keys:
        try:
            wanted.append(key if isinstance(key, uuid.UUID) else uuid.UUID(str(key)))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = await db.scalars(
        select(FileRecord).where(
            FileRecord.id.in_(wanted), FileRecord.deleted_at.is_(None)
        )
    )
    return {row.id: row for row in rows}


async def resource_items_for(
    db: AsyncSession, refs: Sequence[ResourceRef], *, owner: uuid.UUID | None = None
) -> list[RunItem]:
    """开轮引用 → 用户消息里的 item；找不到或非本人文件直接拒绝。

    图片/视频走原生 ImageItem/VideoItem（只存 file_id，回放时按 key 取字节），
    其余文档类才用 <resource/> 标签让模型按需 load_files。
    """
    items: list[RunItem] = []
    resolved = await resolve_resources(db, [ref.storage_key for ref in refs])
    blobs = await _blobs_of(db, [record.blob_hash for record in resolved.values()])
    for ref in refs:
        try:
            record = resolved.get(uuid.UUID(ref.storage_key))
        except ValueError:
            record = None
        if record is None or not _matches_owner(record.owner_id, owner):
            raise UnprocessableError(f"文件 {ref.storage_key} 不存在或已被删除")
        blob = blobs.get(record.blob_hash)
        media_type = record.content_type or "application/octet-stream"
        name = ref.name or record.name
        if media_type.startswith("image/"):
            items.append(
                ImageItem(role="user", file_id=str(record.id), media_type=media_type, alt=name)
            )
        elif media_type.startswith("video/"):
            items.append(
                VideoItem(role="user", file_id=str(record.id), media_type=media_type, alt=name)
            )
        else:
            items.append(
                ResourceItem(
                    role="user",
                    storage_key=str(record.id),
                    name=name,
                    media_type=media_type,
                    size=blob.size if blob is not None else 0,
                )
            )
    return items


async def resolve_attachments(
    db: AsyncSession,
    attachments: Sequence[Attachment],
    *,
    owner: uuid.UUID | None = None,
) -> list[Attachment]:
    """file_id 附件入轮前核归属：名字、mime 和 image/video 类别都以入库记录为准。

    客户端自报的 kind 不可信——拿一张 pdf 的 id 冒充 image 会把请求喂给 provider 才炸。
    """
    if not attachments:
        return []
    resolved = await resolve_resources(db, [item.file_id for item in attachments])
    normalized: list[Attachment] = []
    for attachment in attachments:
        try:
            record = resolved.get(uuid.UUID(attachment.file_id))
        except ValueError:
            record = None
        if record is None or not _matches_owner(record.owner_id, owner):
            raise UnprocessableError(f"附件 {attachment.file_id} 不存在或已被删除")
        media_type = record.content_type or attachment.media_type
        if media_type.startswith("image/"):
            kind = "image"
        elif media_type.startswith("video/"):
            kind = "video"
        else:
            raise UnprocessableError("file_id 附件只支持图片或视频；文档请走 resources 引用")
        normalized.append(
            attachment.model_copy(
                update={"kind": kind, "name": record.name, "media_type": media_type}
            )
        )
    return normalized


async def content_of(
    db: AsyncSession,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    file_id: uuid.UUID,
) -> tuple[bytes, str, str]:
    """同源读取文件字节：浏览器的 fetch 带不了桶的 CORS，307 直链在页面里取不回来。"""
    file = await _owned_file(db, owner, file_id)
    blob = await db.get(Blob, file.blob_hash)
    if blob is None:
        raise GoneError("文件内容已被清理，无法下载")
    data = await storage.get(blob.storage_key)
    return data, file.name, file.content_type or "application/octet-stream"


async def load_media(
    db: AsyncSession,
    file_ids: Sequence[str],
    *,
    storage: ObjectStorage | None = None,
) -> dict[str, tuple[bytes, str]]:
    """按 file_id 批量取媒体字节：回放时把 ImageItem/VideoItem 还原成模型二进制。

    没配存储、记录缺失或内容被清理的 key 直接跳过——回放少一张图好过整轮失败。
    """
    wanted = [fid for fid in dict.fromkeys(file_ids) if fid]
    if not wanted:
        return {}
    if storage is None:
        try:
            storage = get_storage()
        except StorageUnavailableError:
            return {}
    resolved = await resolve_resources(db, wanted)
    records: list[tuple[str, FileRecord]] = []
    for fid in wanted:
        try:
            record = resolved.get(uuid.UUID(fid))
        except ValueError:
            continue
        if record is not None:
            records.append((fid, record))
    blobs = await _blobs_of(db, [record.blob_hash for _, record in records])
    out: dict[str, tuple[bytes, str]] = {}
    for fid, record in records:
        blob = blobs.get(record.blob_hash)
        if blob is None:
            continue
        try:
            data = await storage.get(blob.storage_key)
        except Exception:
            continue
        out[fid] = (data, record.content_type or "application/octet-stream")
    return out


async def visit(
    db: AsyncSession,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    file_id: uuid.UUID,
) -> str:
    """归属校验通过就签一条短时效 URL；307 由端点负责。"""
    file = await _owned_file(db, owner, file_id)
    blob = await db.get(Blob, file.blob_hash)
    if blob is None:
        raise GoneError("文件内容已被清理，无法下载")
    return await storage.url_for(blob.storage_key, download_name=file.name)


async def soft_delete(db: AsyncSession, owner: uuid.UUID | None, file_id: uuid.UUID) -> None:
    file = await _owned_file(db, owner, file_id)
    if file.deleted_at is None:
        file.deleted_at = datetime.now(UTC)
        # 宽限锚点跟着动：最后一次动这个 blob 的引用时间才作数
        await _touch_blob(db, file.blob_hash)
        await db.commit()


async def _owned_session(
    db: AsyncSession, owner: uuid.UUID | None, upload_id: uuid.UUID
) -> UploadSession:
    session = await db.get(UploadSession, upload_id)
    # 归属不符同样 404：不把别人会话的存在性泄露出来
    if session is None or not _matches_owner(session.owner_id, owner):
        raise NotFoundError("上传会话不存在或已失效")
    return session


async def _owned_file(
    db: AsyncSession, owner: uuid.UUID | None, file_id: uuid.UUID
) -> FileRecord:
    file = await db.get(FileRecord, file_id)
    if (
        file is None
        or not _matches_owner(file.owner_id, owner)
        or file.deleted_at is not None
    ):
        raise NotFoundError("文件不存在")
    return file
