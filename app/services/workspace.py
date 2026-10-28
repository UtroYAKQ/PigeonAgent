"""工作区执行环境：本地临时目录或 e2b 兼容沙箱。

文件在上下文里以 ``<resource storage_key=".." original_name=".." mime_type=".."/>``
表示；storage_key 就是 FileRecord 的 id。两种模式的工具形状一致：
load_files 把资源实体化、write_file / read_file / list_files 操作工作区，
沙箱多一个 run_command。run 收尾时把产物上传成 ResourceItem（助手侧）。
"""

from __future__ import annotations

import abc
import logging
import mimetypes
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from app.models.blob import Blob
from app.services import file_service
from app.services.storage import ObjectStorage, safe_name

if TYPE_CHECKING:
    from e2b import AsyncSandbox
    from sqlalchemy.ext.asyncio import AsyncSession
else:  # pragma: no cover - 运行时不强制有 e2b
    AsyncSandbox = Any

# 一层工作的参数上限：模型上下文容不下整个文件，工具结果也别乱铺
_MAX_READ_BYTES = 200_000
_MAX_LOAD_BATCH = 10
_MAX_LIST_ENTRIES = 500
_MAX_COMMAND_OUTPUT = 16_000
_DEFAULT_FILES_DIR = "/home/user/pigeon"

logger = logging.getLogger(__name__)


class WorkspaceError(Exception):
    """工具层统一往外的失败形状：调用方转成 {"error": ...} 喂回模型。"""


def parse_storage_key(key: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(key).strip())
    except ValueError:
        return None


def _relative_clean(name: str) -> PurePosixPath | None:
    """工作区里的相对路径：不许裸空、绝对路径、路径穿越。"""
    cleaned = (name or "").strip().replace("\\", "/")
    pure = PurePosixPath(cleaned)
    if not cleaned or pure.is_absolute() or ".." in pure.parts:
        return None
    return pure


def _unique(path: Path) -> Path:
    """不覆盖已有文件：加 (1)、(2) 后缀。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
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


# --------------------------------------------------------------------- 工作区


class RunWorkspace(abc.ABC):
    """一轮 run 的工作区；生命周期与 execute_run 的 try 块同进退。"""

    def __init__(
        self,
        storage: ObjectStorage | None,
        session_id: uuid.UUID,
        run_id: str,
    ) -> None:
        self.storage = storage
        self.session_id = session_id
        self.run_id = run_id
        # run 收尾要上传的候选；local 模式靠扫目录，sandbox 模式靠记账
        self.produced: set[str] = set()
        # 已经通过 publish_file 单独上传过的相对路径：收产物时跳过，免得上两次
        self.published: set[str] = set()

    def mark_published(self, name: str) -> None:
        pure = _relative_clean(name)
        if pure is not None:
            self.published.add(pure.as_posix())

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """给模型的一句话：这是什么样的工作区，路径怎么写。"""

    def touch(self) -> None:  # noqa: B027 - 本地模式无须刷新，默认空实现
        """工具活动钩子，沙箱模式刷新空闲计时，本地模式无事可做。"""

    @abc.abstractmethod
    async def resolve_keys(
        self, db: AsyncSession, keys: list[str]
    ) -> list[dict[str, Any]]:
        """storage_keys → 实体化记录；没找到的条目带 error 返回，不中断整批。"""

    @abc.abstractmethod
    async def put_file(self, name: str, content: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_file(
        self, name: str, offset: int = 1, limit: int = 200
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_binary(self, name: str) -> bytes:
        """按相对路径读原始字节；文件不存在时抛 WorkspaceError。"""

    @abc.abstractmethod
    async def list_files(self, subdir: str = ".") -> dict[str, Any]: ...

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        return {"error": "当前模式是本地工作区，没有命令执行；配好沙箱（SANDBOX_API_KEY）再来"}

    @abc.abstractmethod
    async def collect_artifacts(self) -> list[tuple[str, bytes, str]]:
        """run 收尾的上传候选：(文件名, 字节, mime)。"""

    async def cleanup(self) -> None:  # noqa: B027 - 沙箱随 kill 一起没，不需要额外清理
        ...


class LocalWorkspace(RunWorkspace):
    """本地模式：后端进程临时目录里的工作区，同进程读写零开销。"""

    def __init__(
        self,
        settings: Any,
        storage: ObjectStorage | None,
        session_id: uuid.UUID,
        run_id: str,
    ) -> None:
        super().__init__(storage, session_id, run_id)
        import tempfile

        base = Path(settings.workspace_root or Path(tempfile.gettempdir()) / "pigeon-workspace")
        self.root = base / str(session_id) / run_id
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def description(self) -> str:
        return "本轮工作区是后端的临时目录（用相对路径读写，load_files 落下来的文件也在这里）。"

    # ------------------------------------------------------------------ 内部
    def _safe(self, name: str) -> Path:
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        return self.root / Path(*pure.parts)

    # ------------------------------------------------------------------ 动作
    async def resolve_keys(self, db: AsyncSession, keys: list[str]) -> list[dict[str, Any]]:
        store = self.storage
        if store is None:
            return [{"storage_key": k, "error": "对象存储未启用，无法加载文件"} for k in keys]
        resolved = await file_service.resolve_resources(db, keys)
        entries: list[dict[str, Any]] = []
        for key in keys[:_MAX_LOAD_BATCH]:
            key = key.strip()
            parsed = parse_storage_key(key)
            record = resolved.get(parsed) if parsed is not None else None
            if record is None:
                entries.append({"storage_key": key, "error": "文件不存在或已被删除"})
                continue
            blob = await db.get(Blob, record.blob_hash)
            if blob is None:
                entries.append({"storage_key": key, "error": "文件内容已被清理"})
                continue
            data = await store.get(blob.storage_key)
            target = _unique(self._safe(record.name))
            target.write_bytes(data)
            entries.append(
                {
                    "storage_key": key,
                    "original_name": record.name,
                    "saved_as": target.relative_to(self.root).as_posix(),
                    "size": len(data),
                }
            )
        if len(keys) > _MAX_LOAD_BATCH:
            entries.append({"error": f"一次最多加载 {_MAX_LOAD_BATCH} 个文件，多出的已忽略"})
        return entries

    async def put_file(self, name: str, content: str) -> dict[str, Any]:
        target = _unique(self._safe(name))
        data = content.encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.produced.add(target.relative_to(self.root).as_posix())
        return {"saved_as": target.relative_to(self.root).as_posix(), "size": len(data)}

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        target = self._safe(name)
        if not target.is_file():
            return {"error": f"{name} 不在工作区里；先用 load_files 或写一个"}
        return text_read(target.read_bytes(), name, offset, limit)

    async def read_binary(self, name: str) -> bytes:
        target = self._safe(name)
        if not target.is_file():
            raise WorkspaceError(f"{name} 不在工作区里；先用 load_files 或写一个")
        return target.read_bytes()

    async def list_files(self, subdir: str = ".") -> dict[str, Any]:
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        base_dir = self.root / Path(*pure.parts)
        if not base_dir.is_dir():
            return {"error": f"{subdir} 不是工作区里的目录"}
        files = [
            {
                "path": child.relative_to(self.root).as_posix(),
                "size": child.stat().st_size,
            }
            for child in sorted(base_dir.rglob("*"))
            if child.is_file()
        ]
        return {"files": files[:_MAX_LIST_ENTRIES], "total": len(files)}

    async def collect_artifacts(self) -> list[tuple[str, bytes, str]]:
        out: list[tuple[str, bytes, str]] = []
        for child in sorted(self.root.rglob("*")):
            if not child.is_file():
                continue
            rel = child.relative_to(self.root).as_posix()
            if rel in self.published:
                continue
            data = child.read_bytes()
            if not data:
                continue
            mime = mimetypes.guess_type(child.name)[0] or "application/octet-stream"
            out.append((rel, data, mime))
        return out

    async def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class SandboxWorkspace(RunWorkspace):
    """e2b 兼容沙箱模式：文件、命令都在远端盘上，工作区目录按 run 隔开。"""

    def __init__(
        self,
        storage: ObjectStorage,
        session_id: uuid.UUID,
        run_id: str,
        sandbox: AsyncSandbox,
        *,
        on_activity: Any | None = None,
    ) -> None:
        super().__init__(storage, session_id, run_id)
        self.storage: ObjectStorage = storage  # 沙箱载文件要从对象存储取字节，无存储不可用
        self.sbx = sandbox
        self.root = f"{_DEFAULT_FILES_DIR}/{run_id}"
        self.on_activity = on_activity
        self.produced_files: list[str] = []

    @property
    def description(self) -> str:
        return (
            f"本轮工作区是云沙箱里的 {self.root}（只允许写这个目录及子目录）："
            "可以跑任意 Linux 命令（run_command），读写文件用 write_file / read_file。"
        )

    # ------------------------------------------------------------------ 内部
    def _mark(self) -> None:
        if callable(self.on_activity):
            self.on_activity()

    def path_in(self, name: str) -> Path:
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        return Path(self.root) / Path(*pure.parts)

    def _abs(self, name: str) -> str:
        return self.path_in(name).as_posix()

    # ------------------------------------------------------------------ 动作
    async def resolve_keys(self, db: AsyncSession, keys: list[str]) -> list[dict[str, Any]]:
        self._mark()
        resolved = await file_service.resolve_resources(db, keys)
        entries: list[dict[str, Any]] = []
        for key in keys[:_MAX_LOAD_BATCH]:
            key = key.strip()
            parsed = parse_storage_key(key)
            record = resolved.get(parsed) if parsed is not None else None
            if record is None:
                entries.append({"storage_key": key, "error": "文件不存在或已被删除"})
                continue
            blob = await db.get(Blob, record.blob_hash)
            if blob is None:
                entries.append({"storage_key": key, "error": "文件内容已被清理"})
                continue
            name = safe_name(record.name)
            # 沙箱不一定连得上对象存储（本地 MinIO / 内网端点），字节走后端中转
            try:
                data = await self.storage.get(blob.storage_key)
                await self.sbx.files.write(self._abs(name), data)
            except Exception as exc:
                logger.exception("Sandbox download failed for %s in run %s", key, self.run_id)
                entries.append({"storage_key": key, "error": f"下载到沙箱失败：{exc}"[:300]})
                continue
            entries.append(
                {
                    "storage_key": key,
                    "original_name": record.name,
                    "saved_as": name,
                    "size": len(data),
                }
            )
        if len(keys) > _MAX_LOAD_BATCH:
            entries.append({"error": f"一次最多加载 {_MAX_LOAD_BATCH} 个文件，多出的已忽略"})
        return entries

    async def put_file(self, name: str, content: str) -> dict[str, Any]:
        self._mark()
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        target = Path(self.root) / Path(*pure.parts)
        await self.sbx.files.write(target.as_posix(), content.encode("utf-8"))
        self.produced.add(pure.as_posix())
        self.produced_files.append(target.as_posix())
        return {"saved_as": pure.as_posix()}

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        self._mark()
        target = self._abs(name)
        try:
            raw = await self.sbx.files.read(target, format="bytes")
        except Exception:
            return {"error": f"沙箱里读不到 {name}；先用 load_files 或 write_file"}
        return text_read(bytes(raw), str(name), offset, limit)

    async def read_binary(self, name: str) -> bytes:
        self._mark()
        target = self._abs(name)
        try:
            raw = await self.sbx.files.read(target, format="bytes")
        except Exception as exc:
            raise WorkspaceError(f"沙箱里读不到 {name}；先用 load_files 或 write_file") from exc
        return bytes(raw)

    async def list_files(self, subdir: str = ".") -> dict[str, Any]:
        self._mark()
        try:
            entries = await self.sbx.files.list(self.path_in(subdir).as_posix())
        except Exception:
            return {"error": f"沙箱里读不到目录 {subdir}"}
        out = []
        for entry in entries:
            name = getattr(entry, "name", None)
            if name is None:
                continue
            out.append({"name": name, "directory": getattr(entry, "is_dir", False)})
        return {"directory": str(subdir), "entries": out[:_MAX_LIST_ENTRIES]}

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        self._mark()
        result = await self.sbx.commands.run(
            command, cwd=self.root, timeout=min(float(timeout_seconds), 600.0)
        )
        stdout = (result.stdout or "")[:_MAX_COMMAND_OUTPUT]
        stderr = (result.stderr or "")[:_MAX_COMMAND_OUTPUT]
        return {"exit_code": result.exit_code, "stdout": stdout, "stderr": stderr}

    async def collect_artifacts(self) -> list[tuple[str, bytes, str]]:
        out: list[tuple[str, bytes, str]] = []
        for path in self.produced_files:
            rel = PurePosixPath(path).relative_to(self.root).as_posix()
            if rel in self.published:
                continue
            try:
                raw = await self.sbx.files.read(path, format="bytes")
            except Exception:
                continue
            payload = bytes(raw)
            if not raw:
                continue
            name = Path(path).name
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            out.append((name, payload, mime))
        return out


async def open_sandbox_workspace(
    storage: ObjectStorage,
    session_id: uuid.UUID,
    run_id: str,
    sandbox: AsyncSandbox,
    *,
    on_activity: Any | None = None,
) -> SandboxWorkspace:
    """接手一个已连接的沙箱，开出本轮工作区目录。"""
    workspace = SandboxWorkspace(storage, session_id, run_id, sandbox, on_activity=on_activity)
    await sandbox.files.make_dir(workspace.root)
    return workspace


def sandbox_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "sandbox_api_key", None))


def _e2b_kwargs(settings: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"api_key": settings.sandbox_api_key}
    if settings.sandbox_api_url:
        kwargs["api_url"] = settings.sandbox_api_url
    if settings.sandbox_domain:
        kwargs["domain"] = settings.sandbox_domain
    return kwargs


async def create_sandbox(settings: Any) -> AsyncSandbox:
    """新建一个 e2b 兼容沙箱；没配 key 直接配置错误。"""
    try:
        from e2b import AsyncSandbox
    except ImportError as exc:  # pragma: no cover - 环境里一律有
        raise WorkspaceError("沙箱 SDK e2b 没安装；先 uv pip install e2b") from exc
    kwargs = _e2b_kwargs(settings)
    if settings.sandbox_template:
        kwargs["template"] = settings.sandbox_template
    # 阿里云 e2b 兼容网关校验 timeout 必须是整数；float 会被 400 拒掉
    kwargs["timeout"] = max(int(settings.sandbox_idle_seconds), 60) + 300
    return await AsyncSandbox.create(**kwargs)


async def connect_sandbox(settings: Any, sandbox_id: str) -> AsyncSandbox:
    """重新接上还活着的沙箱；失败由调用方兜底重建。"""
    from e2b import AsyncSandbox

    return await AsyncSandbox.connect(sandbox_id, **_e2b_kwargs(settings))

