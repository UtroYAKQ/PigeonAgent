"""工作区执行环境：本地临时目录或 e2b 兼容沙箱。

文件在上下文里以 ``<resource storage_key=".." original_name=".." mime_type=".."/>``
表示；storage_key 就是 FileRecord 的 id。两种模式的工具形状一致：
load_files 把资源实体化、write_file / read_file / list_files 操作工作区，
沙箱多一个 run_command。产物只有 publish_file 显式发布才会上传。
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.domain.file_ref import parse_file_id
from app.infra.file_records import resolve_owned_files
from app.infra.storage import ObjectStorage
from app.models.blob import Blob
from app.models.file_record import FileRecord

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
# 从后端把文件写进 envd 的整请求上限；默认 60s 对慢网络下的大文件偏紧。
_SANDBOX_WRITE_TIMEOUT_SECONDS = 180

logger = logging.getLogger(__name__)


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

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """给模型的一句话：这是什么样的工作区，路径怎么写。"""

    def touch(self) -> None:  # noqa: B027 - 本地模式无须刷新，默认空实现
        """工具活动钩子，沙箱模式刷新空闲计时，本地模式无事可做。"""

    @abc.abstractmethod
    async def resolve_files(
        self, db: AsyncSession, file_ids: list[str], *, owner_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """file_id → 实体化记录；只允许会话主人自己的文件。"""

    @abc.abstractmethod
    async def put_file(self, name: str, content: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read_binary(self, name: str, *, max_bytes: int | None = None) -> bytes:
        """按相对路径读原始字节；超过 max_bytes 时抛 WorkspaceError。"""

    @abc.abstractmethod
    async def list_files(self, subdir: str = ".") -> dict[str, Any]: ...

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        return {"error": "当前模式是本地工作区，没有命令执行；配好沙箱（SANDBOX_API_KEY）再来"}

    async def cleanup(self) -> None:  # noqa: B027 - 沙箱随 kill 一起没，不需要额外清理
        ...


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
        parsed = parse_file_id(key)
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

        return await _materialize_load_batch(db, file_ids, owner_id, persist)

    async def put_file(self, name: str, content: str) -> dict[str, Any]:
        data = content.encode("utf-8")

        def _write() -> Path:
            target = self._safe(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return target

        target = await asyncio.to_thread(_write)
        return {"saved_as": target.relative_to(self.root).as_posix(), "size": len(data)}

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        target = self._safe(name)
        if not await asyncio.to_thread(target.is_file):
            return {"error": f"{name} 不在工作区里；先用 load_files 或写一个"}
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

    async def list_files(self, subdir: str = ".") -> dict[str, Any]:
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        base_dir = self.root / Path(*pure.parts)
        if not base_dir.is_dir():
            return {"error": f"{subdir} 不是工作区里的目录"}
        entries = await asyncio.to_thread(_list_children, self.root, base_dir)
        return {"directory": pure.as_posix(), "entries": entries[:_MAX_LIST_ENTRIES]}

    async def cleanup(self) -> None:
        """本轮结束不清目录：目录是按会话分的，删了等于把上一轮写的文件也删了。

        真正的回收放在会话删除时（purge_session_workspace），和沙箱「随会话一起没」对齐。
        """


def _list_children(root: Path, base_dir: Path) -> list[dict[str, Any]]:
    """只列直接子项；stat 是同步调用，统一在 to_thread 里跑。"""
    entries: list[dict[str, Any]] = [
        {
            "name": child.name,
            "path": child.relative_to(root).as_posix(),
            "directory": child.is_dir(),
        }
        for child in base_dir.iterdir()
    ]
    entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
    return entries


def local_workspace_root(settings: Settings, session_id: uuid.UUID) -> Path:
    import tempfile

    base = Path(settings.workspace_root or Path(tempfile.gettempdir()) / "pigeon-workspace")
    return base / str(session_id)


async def purge_session_workspace(settings: Settings, session_id: uuid.UUID) -> None:
    """会话删除时回收它的本地工作区目录；沙箱那边由 pool 的 discard/kill 负责。"""
    await asyncio.to_thread(shutil.rmtree, local_workspace_root(settings, session_id), True)


class SandboxWorkspace(RunWorkspace):
    """e2b 兼容沙箱模式：文件、命令都在远端盘上，工作区目录按会话隔开。

    沙箱按需启动：只有第一次真正调用工具时才向 pool 要容器，之后同一会话内的
    多轮 run 共用同一个容器和同一个目录——上一轮写的文件，下一轮还读得到。
    """

    def __init__(
        self,
        storage: ObjectStorage,
        session_id: uuid.UUID,
        run_id: str,
        sandbox: AsyncSandbox | None = None,
        *,
        sandbox_factory: Callable[[], Awaitable[AsyncSandbox]] | None = None,
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(storage, session_id, run_id)
        self.storage: ObjectStorage = storage  # 沙箱载文件要从对象存储取字节，无存储不可用
        self.sbx = sandbox
        self._sandbox_factory = sandbox_factory
        # 目录按会话划分：同会话多轮共用一个目录，轮次之间文件不会消失
        self.root = f"{_DEFAULT_FILES_DIR}/{session_id}"
        self.on_activity = on_activity

    @property
    def description(self) -> str:
        return (
            f"工作区是云沙箱里的 {self.root}（只允许写这个目录及子目录，同会话跨轮保留）："
            "可以跑任意 Linux 命令（run_command），读写文件用 write_file / read_file。"
        )

    # ------------------------------------------------------------------ 内部
    def _mark(self) -> None:
        if callable(self.on_activity):
            self.on_activity()

    async def _ensure_sandbox(self) -> AsyncSandbox:
        if self.sbx is None:
            if self._sandbox_factory is None:
                raise WorkspaceError("沙箱尚未连接")
            self.sbx = await self._sandbox_factory()
            await self.sbx.files.make_dir(self.root)
        return self.sbx

    def path_in(self, name: str) -> Path:
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        return Path(self.root) / Path(*pure.parts)

    def _abs(self, name: str) -> str:
        return self.path_in(name).as_posix()

    # ------------------------------------------------------------------ 动作
    async def resolve_files(
        self, db: AsyncSession, file_ids: list[str], *, owner_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        self._mark()
        sandbox = await self._ensure_sandbox()

        async def persist(key: str, record: FileRecord, blob: Blob, name: str) -> dict[str, Any]:
            target = self._abs(name)
            try:
                data = await self.storage.get(blob.storage_key)
            except Exception as exc:
                logger.exception("Sandbox storage read failed for %s in run %s", key, self.run_id)
                return {
                    "storage_key": key,
                    "error": f"读取对象存储失败：{exc.__class__.__name__}",
                }
            try:
                await sandbox.files.write(
                    target,
                    data,
                    request_timeout=_SANDBOX_WRITE_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.exception("Sandbox write failed for %s in run %s", key, self.run_id)
                return {
                    "storage_key": key,
                    "error": f"写入沙箱失败：{exc.__class__.__name__}",
                }
            return {
                "storage_key": key,
                "original_name": record.name,
                "saved_as": name,
                "size": blob.size,
            }

        return await _materialize_load_batch(db, file_ids, owner_id, persist)

    async def put_file(self, name: str, content: str) -> dict[str, Any]:
        self._mark()
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        sandbox = await self._ensure_sandbox()
        target = Path(self.root) / Path(*pure.parts)
        if target.parent != Path(self.root):
            # 目录已存在时 make_dir 可能报错；真正的写入失败由 files.write 返回
            with contextlib.suppress(Exception):
                await sandbox.files.make_dir(target.parent.as_posix())
        data = content.encode("utf-8")
        await sandbox.files.write(target.as_posix(), data)
        return {"saved_as": pure.as_posix(), "size": len(data)}

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        self._mark()
        target = self._abs(name)
        sandbox = await self._ensure_sandbox()
        try:
            raw = await sandbox.files.read(target, format="bytes")
        except Exception:
            return {"error": f"沙箱里读不到 {name}；先用 load_files 或 write_file"}
        return text_read(bytes(raw), str(name), offset, limit)

    async def read_binary(self, name: str, *, max_bytes: int | None = None) -> bytes:
        self._mark()
        target = self._abs(name)
        sandbox = await self._ensure_sandbox()
        try:
            # 先查大小再读，别把超限大文件整份拉进后端内存；顺序与本地工作区一致
            if max_bytes is not None:
                info = await sandbox.files.get_info(target)
                if info.size > max_bytes:
                    raise WorkspaceError(f"{name} 超过 {max_bytes // 1024 // 1024} MB 上限")
            raw = await sandbox.files.read(target, format="bytes")
        except WorkspaceError:
            raise
        except Exception as exc:
            raise WorkspaceError(f"沙箱里读不到 {name}；先用 load_files 或 write_file") from exc
        return bytes(raw)

    async def list_files(self, subdir: str = ".") -> dict[str, Any]:
        self._mark()
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        sandbox = await self._ensure_sandbox()
        try:
            raw = await sandbox.files.list(self.path_in(subdir).as_posix())
        except Exception:
            return {"error": f"沙箱里读不到目录 {subdir}"}
        entries: list[dict[str, Any]] = []
        for entry in raw:
            name = getattr(entry, "name", None)
            if not name:
                continue
            entries.append(
                {
                    "name": name,
                    "path": (pure / name).as_posix(),
                    "directory": bool(getattr(entry, "is_dir", False)),
                }
            )
        entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
        return {"directory": pure.as_posix(), "entries": entries[:_MAX_LIST_ENTRIES]}

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        self._mark()
        sandbox = await self._ensure_sandbox()
        result = await sandbox.commands.run(
            command, cwd=self.root, timeout=min(float(timeout_seconds), 600.0)
        )
        stdout = (result.stdout or "")[:_MAX_COMMAND_OUTPUT]
        stderr = (result.stderr or "")[:_MAX_COMMAND_OUTPUT]
        return {"exit_code": result.exit_code, "stdout": stdout, "stderr": stderr}


def sandbox_enabled(settings: Settings) -> bool:
    # 平台总闸优先；SimpleNamespace 类测试配置没有这个字段时按开启处理
    if not getattr(settings, "feature_sandbox_enabled", True):
        return False
    return bool(getattr(settings, "sandbox_api_key", None))


def _e2b_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"api_key": settings.sandbox_api_key}
    if settings.sandbox_api_url:
        kwargs["api_url"] = settings.sandbox_api_url
    if settings.sandbox_domain:
        kwargs["domain"] = settings.sandbox_domain
    return kwargs


def sandbox_ttl(settings: Settings) -> int:
    """上游沙箱的硬存活时长：空闲回收时间再留 5 分钟余量。

    阿里云网关校验 timeout 必须是整数，float 会被 400 拒掉。
    """
    return max(int(settings.sandbox_idle_seconds), 60) + 300


async def create_sandbox(settings: Settings) -> AsyncSandbox:
    """新建一个 e2b 兼容沙箱；没配 key 直接配置错误。"""
    try:
        from e2b import AsyncSandbox
    except ImportError as exc:  # pragma: no cover - 环境里一律有
        raise WorkspaceError("沙箱 SDK e2b 没安装；先 uv pip install e2b") from exc
    kwargs = _e2b_kwargs(settings)
    if settings.sandbox_template:
        kwargs["template"] = settings.sandbox_template
    # 阿里云 e2b 兼容网关校验 timeout 必须是整数；float 会被 400 拒掉
    kwargs["timeout"] = sandbox_ttl(settings)
    return await AsyncSandbox.create(**kwargs)


async def connect_sandbox(settings: Settings, sandbox_id: str) -> AsyncSandbox:
    """重新接上还活着的沙箱；失败由调用方兜底重建。

    必须带 timeout：e2b 的存活时长是从「创建」起算的一次性 TTL，重连不续期的话，
    哪怕每一轮都在用，到了最初的 TTL 也会被上游直接杀掉。
    """
    from e2b import AsyncSandbox

    return await AsyncSandbox.connect(
        sandbox_id, timeout=sandbox_ttl(settings), **_e2b_kwargs(settings)
    )
