"""工作区工具：资源实体化、文件读写，沙箱模式额外有命令执行。

工具闭包绑定一轮 run 的 RunWorkspace；返回纯 dict 喂回模型。
所有失败都走 {"error": ...}，不抛异常打断轮次（WorkspaceError 同样转成败报）。
注意：每个工具都要以 pydantic_ai 能照常取签名的真闭包形式存在，别再套签名借壳。
"""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import PurePosixPath
from typing import Any

from pydantic_ai import Tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services import file_service
from app.services.workspace import RunWorkspace, SandboxWorkspace, WorkspaceError

logger = logging.getLogger(__name__)


def workspace_tools(
    workspace: RunWorkspace,
    factory: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID | None,
    settings: Settings,
) -> list[Tool[Any]]:
    """按模式装配工具闭包；本地和沙箱共用外形，沙箱多一个 run_command。"""

    async def load_files(storage_keys: list[str]) -> dict[str, Any]:
        """把上下文里的 <resource/> 文件按 storage_key 下载到工作区，文件名用 original_name。

        Args:
            storage_keys: resource 标签里的 storage_key 列表（一次最多 10 个）。
        """
        try:
            async with factory() as db:
                entries = await workspace.resolve_keys(db, storage_keys)
        except Exception as exc:
            logger.exception("Workspace tool failed")
            return {"loaded": [], "error": _detail(exc)}
        return {"loaded": entries}

    async def write_file(name: str, content: str) -> dict[str, Any]:
        """在工作区写一个文本文件。

        Args:
            name: 相对工作区根的文件名，比如 report.md。
            content: 完整的文本内容；重复写同名文件会存成 `名 (1).后缀`。
        """
        try:
            result = await workspace.put_file(name, content)
        except Exception as exc:
            logger.exception("Workspace tool failed")
            return {"error": _detail(exc)}
        return result

    async def read_file(name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        """按行范围读工作区里的文本文件，带行号；只读，改文件用 write_file。

        Args:
            name: 相对工作区根的文件名。
            offset: 起始行号（从 1 开始），默认从头。
            limit: 读多少行，默认 200。
        """
        try:
            result = await workspace.read_file(name, offset, limit)
        except Exception as exc:
            logger.exception("Workspace tool failed")
            return {"error": _detail(exc)}
        return result

    async def list_files(subdir: str = ".") -> dict[str, Any]:
        """列工作区目录的内容。

        Args:
            subdir: 相对工作区根的目录，默认整棵工作区。
        """
        try:
            result = await workspace.list_files(subdir)
        except Exception as exc:
            logger.exception("Workspace tool failed")
            return {"error": _detail(exc)}
        return result

    async def publish_file(path: str) -> dict[str, Any]:
        """把工作区里的文件上传到云端存储，用户即可在页面上直接下载。

        Args:
            path: 相对工作区根的文件路径，比如 report.pdf 或 out/chart.png。
        """
        store = workspace.storage
        if store is None:
            return {"error": "对象存储未启用，无法发布文件"}
        try:
            data = await workspace.read_binary(path)
        except Exception as exc:
            return {"error": _detail(exc)}
        if len(data) > settings.max_upload_bytes:
            limit_mb = settings.max_upload_bytes // 1024 // 1024
            return {"error": f"文件超过 {limit_mb} MB 上限，无法发布"}
        name = PurePosixPath(str(path).replace("\\", "/")).name or "file"
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            async with factory() as db:
                record = await file_service.direct_upload(
                    db, settings, store, owner_id, name, mime, data
                )
        except Exception as exc:
            logger.exception("Workspace tool failed")
            return {"error": _detail(exc)}
        workspace.mark_published(path)
        return {
            "storage_key": str(record.id),
            "name": record.name,
            "size": record.size,
            "media_type": record.content_type or mime,
        }

    tools = [
        Tool(load_files),
        Tool(write_file),
        Tool(read_file),
        Tool(list_files),
        Tool(publish_file),
    ]
    if isinstance(workspace, SandboxWorkspace):

        async def run_command(command: str, timeout_seconds: int = 120) -> dict[str, Any]:
            """在沙箱里跑一条 Linux 命令，返回 stdout/stderr/exit_code。

            Args:
                command: 要执行的命令，在本轮工作区目录里执行。
                timeout_seconds: 最长执行秒数，默认 120。
            """
            try:
                result = await workspace.run_command(command, timeout_seconds)
            except Exception as exc:
                logger.exception("Workspace tool failed")
                return {"error": _detail(exc)}
            return result

        tools.append(Tool(run_command))
    return tools


def _detail(exc: Exception) -> str:
    """单条错误文案：預期内的 WorkspaceError 用原话，其余瘦身到 500 字。"""
    if isinstance(exc, WorkspaceError):
        return str(exc)
    logger.debug("Workspace tool traceback", exc_info=exc)
    return f"{type(exc).__name__}: {exc}"[:500]


def workspace_instructions() -> str:
    """提示词里的资源约定段，追加在 agent instructions 后面。"""
    return (
        "## 文件资源\n"
        "会话里的文件、图片和视频都以 "
        "<resource storage_key=\"..\" original_name=\"..\" mime_type=\"..\"/> 表示："
        "storage_key 是取用凭据，original_name 是给用户的文件名；"
        "图片/视频的内容同时会直接展示给你。"
        "要把文件（含图片/视频）落进本轮工作区处理，"
        "先调 load_files（把 storage_key 传进去），"
        "它会以 original_name 落进工作区，之后的 write_file / read_file 都用相对路径。"
        "你新写出的文件会在本轮结束后自动上传成为新的 <resource/>，可以下载；"
        "想让用户马上拿到某个文件（包括 run_command 生成的产物），用 publish_file 发布，"
        "它会返回 storage_key，前端会显示下载入口。"
        "需要看文本内容时用 read_file 范围读取。"
    )
