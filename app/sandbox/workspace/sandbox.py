"""云端工作区：e2b 兼容沙箱，按会话隔离并按需启动。"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import logging
import re
import shlex
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.infra.files.storage import ObjectStorage
from app.sandbox.workspace.base import RunWorkspace
from app.sandbox.workspace.common import (
    _DEFAULT_FILES_DIR,
    _GREP_LINE_CHARS,
    _MAX_GREP_RESULTS,
    _MAX_LIST_ENTRIES,
    _MAX_READ_BYTES,
    _SANDBOX_WRITE_TIMEOUT_SECONDS,
    LoadJob,
    WorkspaceError,
    _materialize_load_batch,
    _relative_clean,
    clip_output,
    text_view,
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
            "可以跑任意 Linux 命令（run_command），也可以用 run_script 一次执行 Python；"
            "读写文件用 write_file / read_file，找内容用 grep_files。"
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

        async def persist_many(jobs: list[LoadJob]) -> list[dict[str, Any]]:
            fetched = await asyncio.gather(
                *(self.storage.get(job[2].storage_key) for job in jobs),
                return_exceptions=True,
            )
            results: list[dict[str, Any] | None] = [None] * len(jobs)
            writes: list[tuple[int, str, bytes]] = []
            for index, (job, data) in enumerate(zip(jobs, fetched, strict=True)):
                key, _record, _blob, name = job
                if isinstance(data, asyncio.CancelledError):
                    raise data
                if isinstance(data, BaseException):
                    logger.error(
                        "Sandbox storage read failed for %s in run %s",
                        key,
                        self.run_id,
                        exc_info=(type(data), data, data.__traceback__),
                    )
                    results[index] = {
                        "storage_key": key,
                        "error": f"读取对象存储失败：{data.__class__.__name__}",
                    }
                    continue
                writes.append((index, self._abs(name), bytes(data)))

            def succeed(index: int, size: int) -> None:
                key, record, _blob, name = jobs[index]
                results[index] = {
                    "storage_key": key,
                    "original_name": record.name,
                    "saved_as": name,
                    "size": size,
                }

            if writes:
                try:
                    await sandbox.files.write_files(
                        [{"path": path, "data": data} for _, path, data in writes],
                        request_timeout=_SANDBOX_WRITE_TIMEOUT_SECONDS,
                    )
                except Exception:
                    # 批量写失败时逐条重试，保留每一行具体失败原因
                    for index, path, data in writes:
                        try:
                            await sandbox.files.write(
                                path, data, request_timeout=_SANDBOX_WRITE_TIMEOUT_SECONDS
                            )
                        except Exception as exc:
                            key = jobs[index][0]
                            logger.exception(
                                "Sandbox write failed for %s in run %s", key, self.run_id
                            )
                            results[index] = {
                                "storage_key": key,
                                "error": f"写入沙箱失败：{exc.__class__.__name__}",
                            }
                        else:
                            succeed(index, len(data))
                else:
                    for index, _path, data in writes:
                        succeed(index, len(data))
            return [entry for entry in results if entry is not None]

        return await _materialize_load_batch(db, file_ids, owner_id, persist_many=persist_many)

    async def put_file(self, name: str, content: str, *, append: bool = False) -> dict[str, Any]:
        self._mark()
        pure = _relative_clean(name)
        if pure is None:
            raise WorkspaceError(f"非法路径：{name!r}")
        sandbox = await self._ensure_sandbox()
        target = (Path(self.root) / Path(*pure.parts)).as_posix()
        data = content.encode("utf-8")
        if append:
            await self._append_bytes(sandbox, target, data, name)
        else:
            await sandbox.files.write(target, data, request_timeout=_SANDBOX_WRITE_TIMEOUT_SECONDS)
        return {"saved_as": pure.as_posix(), "size": len(data), "append": append}

    async def _append_bytes(
        self, sandbox: AsyncSandbox, target: str, data: bytes, name: str
    ) -> None:
        """只上传新增字节，在沙箱里就地追加；不再把原文件整份读回来。"""
        tmp = f"{target}.part-{uuid.uuid4().hex}"
        await sandbox.files.write(tmp, data, request_timeout=_SANDBOX_WRITE_TIMEOUT_SECONDS)
        command = (
            f"if [ ! -f {shlex.quote(target)} ]; then rm -f {shlex.quote(tmp)}; exit 3; fi; "
            f"cat {shlex.quote(tmp)} >> {shlex.quote(target)} && rm -f {shlex.quote(tmp)}"
        )
        result: Any = None
        try:
            result = await sandbox.commands.run(command, cwd=self.root, timeout=30)
            exit_code: int | None = getattr(result, "exit_code", 0)
        except Exception as exc:
            exit_code = getattr(exc, "exit_code", None)
            if exit_code is None:
                raise WorkspaceError(f"追加写入沙箱失败：{exc.__class__.__name__}") from exc
        if exit_code == 3:
            raise WorkspaceError(f"{name} 还不存在；第一次写入请用 append=false")
        if exit_code != 0 or result is None:
            with contextlib.suppress(Exception):
                await sandbox.commands.run(f"rm -f {shlex.quote(tmp)}", cwd=self.root, timeout=30)
            raise WorkspaceError(f"追加写入沙箱失败（exit {exit_code}）")

    async def read_file(self, name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        self._mark()
        target = self._abs(name)
        sandbox = await self._ensure_sandbox()
        return await self._read_lines(sandbox, target, name, offset, limit)

    async def _read_lines(
        self,
        sandbox: AsyncSandbox,
        target: str,
        name: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        """在沙箱里用 awk 只取目标行，不再把整份文件拉回后端。"""
        start = max(1, offset)
        end = start - 1 + max(1, limit)
        program = 'NR>=s && NR<=e {print} END {printf "__PIGEON_TOTAL__%d\\n", NR}'
        command = (
            f"LC_ALL=C awk -v s={start} -v e={end} {shlex.quote(program)} {shlex.quote(target)}"
        )
        result: Any = None
        try:
            result = await sandbox.commands.run(command, cwd=self.root, timeout=30)
            exit_code = getattr(result, "exit_code", 0)
        except Exception as exc:
            exit_code = getattr(exc, "exit_code", None)
            if exit_code is None:
                raise WorkspaceError(f"读取沙箱文件失败：{exc.__class__.__name__}") from exc
        if exit_code == 2:
            return await self._file_missing(name)
        if exit_code != 0 or result is None:
            raise WorkspaceError(f"读取沙箱文件失败（exit {exit_code}）")

        lines = (result.stdout or "").splitlines()
        total = start - 1 + len(lines)
        if lines and lines[-1].startswith("__PIGEON_TOTAL__"):
            with contextlib.suppress(ValueError):
                total = int(lines[-1].removeprefix("__PIGEON_TOTAL__"))
            lines.pop()
        raw = "\n".join(lines)
        if "\x00" in raw[:4096]:
            return {"error": f"{name} 是二进制文件，这个工具读不了"}
        return text_view(
            raw[:_MAX_READ_BYTES].splitlines(),
            name,
            offset,
            limit,
            total=total,
            first_line=start,
        )

    async def _file_missing(self, name: str) -> dict[str, Any]:
        available: list[Any] = []
        with contextlib.suppress(Exception):
            listing = await self.list_files()
            available = listing.get("entries", [])
        return {
            "error": f"沙箱里读不到 {name}；先用 load_files 或 write_file",
            "available": available,
        }

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

    async def list_files(
        self,
        subdir: str = ".",
        *,
        pattern: str | None = None,
        recursive: bool = False,
    ) -> dict[str, Any]:
        self._mark()
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        sandbox = await self._ensure_sandbox()
        if recursive:
            return await self._list_tree(sandbox, pure, pattern)
        try:
            raw = await sandbox.files.list(self.path_in(subdir).as_posix())
        except Exception:
            return {"error": f"沙箱里读不到目录 {subdir}"}
        entries: list[dict[str, Any]] = []
        for entry in raw:
            name = getattr(entry, "name", None)
            if not name or (pattern and not fnmatch.fnmatch(name, pattern)):
                continue
            entries.append(
                {
                    "name": name,
                    "path": (pure / name).as_posix(),
                    "directory": bool(getattr(entry, "is_dir", False)),
                }
            )
        entries.sort(key=lambda item: (not item["directory"], item["path"].casefold()))
        return {
            "directory": pure.as_posix(),
            "entries": entries[:_MAX_LIST_ENTRIES],
            "truncated": len(entries) > _MAX_LIST_ENTRIES,
        }

    async def _list_tree(
        self,
        sandbox: AsyncSandbox,
        base: PurePosixPath,
        pattern: str | None,
    ) -> dict[str, Any]:
        base_abs = (Path(self.root) / Path(*base.parts)).as_posix()
        name_filter = f" -name {shlex.quote(pattern)}" if pattern else ""
        command = (
            f"find {shlex.quote(base_abs)} -mindepth 1 -maxdepth 10{name_filter} "
            f"-printf '%y\\t%P\\n' | head -n {_MAX_LIST_ENTRIES + 1}"
        )
        try:
            result = await sandbox.commands.run(command, cwd=self.root, timeout=30)
        except Exception:
            return {"error": f"{base.as_posix()} 不是工作区里的目录"}
        entries: list[dict[str, Any]] = []
        for line in (result.stdout or "").splitlines():
            kind, sep, relative = line.partition("\t")
            if not sep or not relative:
                continue
            entries.append(
                {
                    "name": PurePosixPath(relative).name,
                    "path": (base / relative).as_posix(),
                    "directory": kind == "d",
                }
            )
        entries.sort(key=lambda item: (not item["directory"], item["path"].casefold()))
        return {
            "directory": base.as_posix(),
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
        self._mark()
        pure = _relative_clean(subdir)
        if pure is None:
            return {"error": f"非法路径：{subdir!r}"}
        try:
            re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"正则表达式无效：{exc}") from exc
        limit = max(1, min(int(max_results), _MAX_GREP_RESULTS))
        sandbox = await self._ensure_sandbox()
        base = (Path(self.root) / Path(*pure.parts)).as_posix()
        include = f" --include={shlex.quote(glob)}" if glob else ""
        command = (
            f"if [ ! -d {shlex.quote(base)} ]; then echo __PIGEON_NO_DIR__; exit 0; fi; "
            f"grep -rInZE{include} -e {shlex.quote(pattern)} {shlex.quote(pure.as_posix())} "
            f"| head -n {limit + 1}"
        )
        try:
            result = await sandbox.commands.run(command, cwd=self.root, timeout=30)
        except Exception as exc:
            raise WorkspaceError(f"沙箱检索失败：{exc.__class__.__name__}") from exc
        output = result.stdout or ""
        if "__PIGEON_NO_DIR__" in output:
            return {"error": f"{subdir} 不是工作区里的目录"}
        matches: list[dict[str, Any]] = []
        lines = output.splitlines()
        for line in lines[:limit]:
            path, sep, rest = line.partition("\0")
            lineno, sep2, text = rest.partition(":")
            if not sep or not sep2:
                continue
            matches.append(
                {
                    "path": path.removeprefix("./"),
                    "line": int(lineno) if lineno.isdigit() else 0,
                    "text": text[:_GREP_LINE_CHARS],
                }
            )
        return {"matches": matches, "count": len(matches), "truncated": len(lines) > limit}

    async def run_command(self, command: str, timeout_seconds: int = 120) -> dict[str, Any]:
        self._mark()
        sandbox = await self._ensure_sandbox()
        return await self._run_shell(sandbox, command, timeout_seconds)

    async def run_script(self, code: str, timeout_seconds: int = 120) -> dict[str, Any]:
        self._mark()
        sandbox = await self._ensure_sandbox()
        return await self._run_shell(sandbox, f"python3 -c {shlex.quote(code)}", timeout_seconds)

    async def _run_shell(
        self, sandbox: AsyncSandbox, command: str, timeout_seconds: int
    ) -> dict[str, Any]:
        result = await sandbox.commands.run(
            command, cwd=self.root, timeout=min(float(timeout_seconds), 600.0)
        )
        stdout, stdout_truncated = clip_output(result.stdout or "")
        stderr, stderr_truncated = clip_output(result.stderr or "")
        return {
            "exit_code": result.exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": stdout_truncated or stderr_truncated,
        }


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
