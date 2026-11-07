"""工作区两种实现共用的路径、读取与资源实体化规则。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from app.core.ids import parse_uuid
from app.infra.files.records import resolve_owned_files
from app.models.files.blob import Blob
from app.models.files.record import FileRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_READ_BYTES = 200_000

_MAX_LOAD_BATCH = 10

_MAX_LIST_ENTRIES = 500

_MAX_COMMAND_OUTPUT = 16_000

_DEFAULT_FILES_DIR = "/home/user/pigeon"

_SANDBOX_WRITE_TIMEOUT_SECONDS = 180


class WorkspaceError(Exception):
    """工具层统一往外的失败形状：调用方转成 {"error": ...} 喂回模型。"""


def _relative_clean(name: str) -> PurePosixPath | None:
    """工作区里的相对路径：不许裸空、绝对路径、路径穿越。"""
    cleaned = (name or "").strip().replace("\\", "/")
    pure = PurePosixPath(cleaned)
    if not cleaned or pure.is_absolute() or ".." in pure.parts:
        return None
    return pure


def _unique_name(name: str, used: set[str]) -> str:
    """批次内重名时加 (1)、(2) 后缀，两套工作区共用同一命名规则。"""
    if name not in used:
        return name
    pure = PurePosixPath(name)
    index = 1
    while True:
        candidate = f"{pure.stem} ({index}){pure.suffix}"
        if candidate not in used:
            return candidate
        index += 1


def text_read(data: bytes, name: str, offset: int, limit: int) -> dict[str, Any]:
    """范围读正文：1 起始行号，超界给空并提示；二进制拒绝。"""
    payload = bytes(data)
    if b"\x00" in payload[:4096]:
        return {"error": f"{name} 是二进制文件，这个工具读不了"}
    text = data.decode("utf-8", errors="replace")[:_MAX_READ_BYTES]
    lines = text.splitlines()
    total = len(lines)
    start = max(1, offset)
    end = min(total, start - 1 + max(1, limit))
    if start > total:
        return {
            "name": name,
            "error": f"正文只有 {total} 行；offset 从 1 开始",
            "total_lines": total,
        }
    numbered = [f"{index:6d}: {lines[index - 1]}" for index in range(start, end + 1)]
    return {
        "name": name,
        "total_lines": total,
        "start_line": start,
        "end_line": end,
        "lines": numbered,
        "hint": "还有更多行" if end < total else "已到文件尾",
    }


async def _materialize_load_batch(
    db: AsyncSession,
    file_ids: list[str],
    owner_id: uuid.UUID | None,
    persist: Callable[[str, FileRecord, Blob, str], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """load_files 的共用流程：批次截断、owner 过滤、Blob 校验、重名和失败行构造。

    两种工作区只有「字节落到哪」不同（本地写目录 / 沙箱推远端），其余逐字一致，
    差异收进 persist 回调；persist 返回这一条 key 的成功或失败条目。
    """
    resolved = await resolve_owned_files(db, file_ids, owner_id=owner_id)
    entries: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for file_id in file_ids[:_MAX_LOAD_BATCH]:
        key = file_id.strip()
        parsed = parse_uuid(key)
        record = resolved.get(parsed) if parsed is not None else None
        if record is None:
            entries.append({"storage_key": key, "error": "文件不存在或已被删除"})
            continue
        blob = await db.get(Blob, record.blob_hash)
        if blob is None:
            entries.append({"storage_key": key, "error": "文件内容已被清理"})
            continue
        name = _unique_name(record.name, used_names)
        used_names.add(name)
        entries.append(await persist(key, record, blob, name))
    if len(file_ids) > _MAX_LOAD_BATCH:
        entries.append({"error": f"一次最多加载 {_MAX_LOAD_BATCH} 个文件，多出的已忽略"})
    return entries
