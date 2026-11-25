"""本地工作区：后端进程临时目录，同会话跨轮保留。"""

from __future__ import annotations

import asyncio
import fnmatch
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.infra.files.storage import ObjectStorage
from app.models.files.blob import Blob
from app.models.files.record import FileRecord
from app.sandbox.workspace.base import RunWorkspace
from app.sandbox.workspace.common import (
    _GREP_LINE_CHARS,
    _MAX_GREP_RESULTS,
    _MAX_LIST_ENTRIES,
    WorkspaceError,
    _materialize_load_batch,
    _relative_clean,
    text_read,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class LocalWorkspace(RunWorkspace):
    """本地模式：后端进程临时目录里的工作区，同进程读写零开销。"""

    def __init__(
        self,
        settings: Settings,
        storage: ObjectStorage | None,
        session_id: uuid.UUID,
        run_id: str,
    ) -> None:
        super().__init__(storage, session_id, run_id)
        # 同会话同目录：每轮换目录等于每轮清空，模型上一轮写的文件下一轮就没了
        self.root = local_workspace_root(settings, session_id)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def description(self) -> str:
        return "工作区是后端的临时目录（用相对路径读写，load_files 落下来的文件也在这里）。"

    # ------------------------------------------------------------------ 内部
    def _safe(self, name: str) -> Path:
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        return self.root / Path(*pure.parts)

    # ------------------------------------------------------------------ 动作
    async def resolve_files(
        self, db: AsyncSession, file_ids: list[str], *, owner_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        store = self.storage
        if store is None:
            return [{"storage_key": k, "error": "对象存储未启用，无法加载文件"} for k in file_ids]

        async def persist(key: str, record: FileRecord, blob: Blob, name: str) -> dict[str, Any]:
            data = await store.get(blob.storage_key)
            target = self._safe(name)

            def _write() -> None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            await asyncio.to_thread(_write)
            return {
                "storage_key": key,
                "original_name": record.name,
                "saved_as": target.relative_to(self.root).as_posix(),
                "size": len(data),
            }

        return await _materialize_load_batch(db, file_ids, owner_id, persist=persist)

    async def put_file(self, name: str, content: str, *, append: bool = False) -> dict[str, Any]:
        data = content.encode("utf-8")

        def _write() -> Path:
            target = self._safe(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if append and not target.is_file():
                raise WorkspaceError(f"{name} 还不存在；第一次写入请用 append=false")
            with target.open("ab" if append else "wb") as handle:
                handle.write(data)
            return target

        target = await asyncio.to_thread(_write)
        return {
            "saved_as": target.relative_to(self.root).as_posix(),
            "size": len(data),
            "append": append,
        }

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        target = self._safe(name)
        if not await asyncio.to_thread(target.is_file):
            listing = await self.list_files()
            return {
                "error": f"{name} 不在工作区里；先用 load_files 或写一个",
                "available": listing.get("entries", []),
            }
        data = await asyncio.to_thread(target.read_bytes)
        return text_read(data, name, offset, limit)

    async def read_binary(self, name: str, *, max_bytes: int | None = None) -> bytes:
        target = self._safe(name)
        if not await asyncio.to_thread(target.is_file):
            raise WorkspaceError(f"{name} 不在工作区里；先用 load_files 或写一个")
        if max_bytes is not None:
            size = (await asyncio.to_thread(target.stat)).st_size
            if size > max_bytes:
                raise WorkspaceError(f"{name} 超过 {max_bytes // 1024 // 1024} MB 上限")
        return await asyncio.to_thread(target.read_bytes)

    async def list_files(
        self,
        subdir: str = ".",
        *,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> dict[str, Any]:
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        base_dir = self.root / Path(*pure.parts)
        if not base_dir.is_dir():
            return {"error": f"{subdir} 不是工作区里的目录"}
        entries = await asyncio.to_thread(_list_children, self.root, base_dir, pattern, recursive)
        return {
            "directory": pure.as_posix(),
            "entries": entries[:_MAX_LIST_ENTRIES],
            "truncated": len(entries) > _MAX_LIST_ENTRIES,
        }

    async def grep_files(
        self,
        pattern: str,
        subdir: str = ".",
        glob: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        base_dir = self.root / Path(*pure.parts)
        if not base_dir.is_dir():
            return {"error": f"{subdir} 不是工作区里的目录"}
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"正则表达式无效：{exc}") from exc
        limit = max(1, min(int(max_results), _MAX_GREP_RESULTS))
        return await asyncio.to_thread(_grep_tree, self.root, base_dir, regex, glob, limit)

    async def cleanup(self) -> None:
        """本轮结束不清目录：目录是按会话分的，删了等于把上一轮写的文件也删了。

        真正的回收放在会话删除时（purge_session_workspace），和沙箱「随会话一起没」对齐。
        """


def _list_children(
    root: Path,
    base_dir: Path,
    pattern: str | None,
    recursive: bool,
) -> list[dict[str, Any]]:
    """列子项；递归与通配符过滤都在 to_thread 里做，避免逐条异步往返。"""
    children = base_dir.rglob("*") if recursive else base_dir.iterdir()
    entries: list[dict[str, Any]] = []
    for child in children:
        relative = child.relative_to(root).as_posix()
        if pattern and not (
            fnmatch.fnmatch(child.name, pattern) or fnmatch.fnmatch(relative, pattern)
        ):
            continue
        entries.append(
            {
                "name": child.name,
                "path": relative,
                "directory": child.is_dir(),
            }
        )
    entries.sort(key=lambda item: (not item["directory"], item["path"].casefold()))
    return entries


def _grep_tree(
    root: Path,
    base_dir: Path,
    regex: re.Pattern[str],
    glob: str | None,
    limit: int,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if glob and not (fnmatch.fnmatch(path.name, glob) or fnmatch.fnmatch(relative, glob)):
            continue
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            continue
        for lineno, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if not regex.search(line):
                continue
            if len(matches) >= limit:
                return {"matches": matches, "count": len(matches), "truncated": True}
            matches.append({"path": relative, "line": lineno, "text": line[:_GREP_LINE_CHARS]})
    return {"matches": matches, "count": len(matches), "truncated": False}


def local_workspace_root(settings: Settings, session_id: uuid.UUID) -> Path:
    import tempfile

    base = Path(settings.workspace_root or Path(tempfile.gettempdir()) / "pigeon-workspace")
    return base / str(session_id)


async def purge_session_workspace(settings: Settings, session_id: uuid.UUID) -> None:
    """会话删除时回收它的本地工作区目录；沙箱那边由 pool 的 discard/kill 负责。"""
    await asyncio.to_thread(shutil.rmtree, local_workspace_root(settings, session_id), True)
