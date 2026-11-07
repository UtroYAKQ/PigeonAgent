"""文件内容：媒体回放、引用物化与签名下载。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    GoneError,
    NotFoundError,
    StorageUnavailableError,
    UnprocessableError,
)
from app.core.ids import parse_uuid
from app.domain.media.media_type import effective_media_type
from app.domain.run_items import ImageItem, ResourceItem, RunItem, VideoItem
from app.infra.files.records import resolve_files, resolve_owned_files
from app.infra.files.storage import ObjectStorage, get_storage
from app.models.files.blob import Blob
from app.models.files.record import FileRecord
from app.schemas.run import Attachment, ResourceRef
from app.services.file_service.records import _blobs_of, _owned_file

logger = logging.getLogger(__name__)

_MEDIA_CACHE_MAX_BYTES = 128 * 1024 * 1024

_MEDIA_CACHE_TTL_SECONDS = 600

_MEDIA_FETCH_CONCURRENCY = 8
_media_cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
_media_cache_bytes = 0


def clear_media_cache() -> None:
    """测试与运行期维护用：丢掉当前 worker 的所有媒体缓存。"""
    global _media_cache_bytes
    _media_cache.clear()
    _media_cache_bytes = 0


def _cache_get(file_id: str, now: float) -> bytes | None:
    entry = _media_cache.get(file_id)
    if entry is None:
        return None
    expires_at, data = entry
    if expires_at <= now:
        _cache_drop(file_id)
        return None
    _media_cache.move_to_end(file_id)
    return data


def _cache_put(file_id: str, data: bytes, now: float) -> None:
    global _media_cache_bytes
    if len(data) > _MEDIA_CACHE_MAX_BYTES:
        return
    _cache_drop(file_id)
    _media_cache[file_id] = (now + _MEDIA_CACHE_TTL_SECONDS, data)
    _media_cache_bytes += len(data)
    while _media_cache_bytes > _MEDIA_CACHE_MAX_BYTES:
        _, dropped = _media_cache.popitem(last=False)
        _media_cache_bytes -= len(dropped[1])


def _cache_drop(file_id: str) -> None:
    global _media_cache_bytes
    entry = _media_cache.pop(file_id, None)
    if entry is not None:
        _media_cache_bytes -= len(entry[1])


async def resource_items_for(
    db: AsyncSession, refs: Sequence[ResourceRef], *, owner: uuid.UUID | None = None
) -> list[RunItem]:
    """开轮引用 → 用户消息里的 item；找不到或非本人文件直接拒绝。

    图片/视频走原生 ImageItem/VideoItem（只存 file_id，回放时按 key 取字节），
    其余文档类才用 <resource/> 标签让模型按需 load_files。
    """
    items: list[RunItem] = []
    resolved = await resolve_owned_files(db, [ref.file_id for ref in refs], owner_id=owner)
    blobs = await _blobs_of(db, [record.blob_hash for record in resolved.values()])
    for ref in refs:
        parsed = parse_uuid(ref.file_id)
        record = resolved.get(parsed) if parsed is not None else None
        if record is None:
            raise UnprocessableError(f"文件 {ref.file_id} 不存在或已被删除")
        blob = blobs.get(record.blob_hash)
        media_type = effective_media_type(record.name, record.content_type)
        name = ref.name or record.name
        kind = _media_kind(media_type)
        if kind is None:
            items.append(
                ResourceItem(
                    role="user",
                    file_id=str(record.id),
                    name=name,
                    media_type=media_type,
                    size=blob.size if blob is not None else 0,
                )
            )
        else:
            item_type = ImageItem if kind == "image" else VideoItem
            items.append(
                item_type(
                    role="user",
                    file_id=str(record.id),
                    name=name,
                    media_type=media_type,
                    alt=name,
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
    resolved = await resolve_owned_files(db, [item.file_id for item in attachments], owner_id=owner)
    normalized: list[Attachment] = []
    for attachment in attachments:
        parsed = parse_uuid(attachment.file_id)
        record = resolved.get(parsed) if parsed is not None else None
        if record is None:
            raise UnprocessableError(f"附件 {attachment.file_id} 不存在或已被删除")
        media_type = effective_media_type(record.name, record.content_type)
        kind = _media_kind(media_type)
        if kind is None:
            raise UnprocessableError("附件只支持图片或视频；文档请走 resources 引用")
        normalized.append(
            attachment.model_copy(
                update={"kind": kind, "name": record.name, "media_type": media_type}
            )
        )
    return normalized


def _media_kind(media_type: str) -> Literal["image", "video"] | None:
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"
    return None


async def assert_readable(
    db: AsyncSession, owner: uuid.UUID | None, file_id: uuid.UUID
) -> FileRecord:
    """只校验归属不读字节：签一条直链这种轻量入口用得上。"""
    return await _owned_file(db, owner, file_id)


async def readable(db: AsyncSession, file_id: uuid.UUID) -> FileRecord:
    """签名链接的读取入口：能力已经在签名里，不再校验归属，但仍要求文件未软删。"""
    file = await db.get(FileRecord, file_id)
    if file is None or file.deleted_at is not None:
        raise NotFoundError("文件不存在")
    return file


async def presigned_for(
    db: AsyncSession,
    storage: ObjectStorage,
    file: FileRecord,
    *,
    inline: bool,
    ttl_seconds: int | None = None,
) -> str:
    """给一条文件记录签短时效 GET；inline 时让浏览器按原 Content-Type 直接渲染。"""
    blob = await db.get(Blob, file.blob_hash)
    if blob is None:
        raise GoneError("文件内容已被清理，无法下载")
    content_type = effective_media_type(file.name, file.content_type)
    return await storage.url_for(
        blob.storage_key,
        download_name=file.name,
        inline=inline,
        content_type=content_type if inline else None,
        ttl_seconds=ttl_seconds,
    )


async def content_of(
    db: AsyncSession,
    storage: ObjectStorage,
    owner: uuid.UUID | None,
    file_id: uuid.UUID,
) -> tuple[bytes, str, str, str]:
    """同源读取文件字节：浏览器的 fetch 带不了桶的 CORS，307 直链在页面里取不回来。

    返回的最后一个值是内容 sha256；文件记录指向的字节不会变，可直接当强 ETag。
    """
    file = await _owned_file(db, owner, file_id)
    blob = await db.get(Blob, file.blob_hash)
    if blob is None:
        raise GoneError("文件内容已被清理，无法下载")
    data = await storage.get(blob.storage_key)
    return (
        data,
        file.name,
        effective_media_type(file.name, file.content_type, data),
        file.blob_hash,
    )


async def load_media(
    db: AsyncSession,
    file_ids: Sequence[str],
    *,
    storage: ObjectStorage | None = None,
) -> dict[str, bytes]:
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
    resolved = await resolve_files(db, wanted)
    records: list[tuple[str, FileRecord]] = []
    for fid in wanted:
        parsed = parse_uuid(fid)
        if parsed is None:
            logger.warning("Replay skipped file %s: not a file id", fid)
            continue
        record = resolved.get(parsed)
        if record is not None:
            records.append((fid, record))
    blobs = await _blobs_of(db, [record.blob_hash for _, record in records])
    now = time.monotonic()
    out: dict[str, bytes] = {}
    missing: list[tuple[str, str]] = []
    for fid, record in records:
        blob = blobs.get(record.blob_hash)
        if blob is None:
            logger.warning("Replay skipped file %s: blob %s is gone", fid, record.blob_hash)
            continue
        cached = _cache_get(fid, now)
        if cached is not None:
            out[fid] = cached
        else:
            missing.append((fid, blob.storage_key))

    if missing:
        semaphore = asyncio.Semaphore(_MEDIA_FETCH_CONCURRENCY)

        async def fetch(fid: str, storage_key: str) -> tuple[str, bytes | None]:
            async with semaphore:
                try:
                    return fid, await storage.get(storage_key)
                except Exception:
                    # 少一张图好过整轮失败，但要能在日志里看出少了哪张、为什么少
                    logger.exception("Replay skipped file %s: storage read failed", fid)
                    return fid, None

        fetched = await asyncio.gather(*(fetch(fid, key) for fid, key in missing))
        for fid, data in fetched:
            if data is None:
                continue
            out[fid] = data
            _cache_put(fid, data, now)
    return out
