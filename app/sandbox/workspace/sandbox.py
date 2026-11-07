"""云端工作区：e2b 兼容沙箱，按会话隔离并按需启动。"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.infra.files.storage import ObjectStorage
from app.models.files.blob import Blob
from app.models.files.record import FileRecord
from app.sandbox.workspace.base import RunWorkspace
from app.sandbox.workspace.common import (
    _DEFAULT_FILES_DIR,
    _MAX_COMMAND_OUTPUT,
    _MAX_LIST_ENTRIES,
    _SANDBOX_WRITE_TIMEOUT_SECONDS,
    WorkspaceError,
    _materialize_load_batch,
    _relative_clean,
    text_read,
)

if TYPE_CHECKING:
    from e2b import AsyncSandbox
    from sqlalchemy.ext.asyncio import AsyncSession
else:  # pragma: no cover - 运行时不强制有 e2b
    AsyncSandbox = Any

logger = logging.getLogger(__name__)


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


def can_use_sandbox(settings: Settings) -> bool:
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
