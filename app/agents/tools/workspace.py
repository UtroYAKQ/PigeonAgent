"""工作区工具：资源实体化、文件读写，沙箱模式额外有命令执行。

工具闭包绑定一轮 run 的 RunWorkspace；返回纯 dict 喂回模型。
所有失败都走 {"error": ...}，不抛异常打断轮次（WorkspaceError 同样转成败报）。
注意：每个工具都要以 pydantic_ai 能照常取签名的真闭包形式存在，别再套签名借壳。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import PurePosixPath
from typing import Any

from pydantic_ai import RunContext, Tool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.protocol.events import ArtifactEvent, ArtifactMedia
from app.core.config import Settings
from app.core.exceptions import describe_error
from app.domain.media.media_type import effective_media_type
from app.sandbox.workspace import RunWorkspace, SandboxWorkspace, WorkspaceError
from app.services import file_service

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
                entries = await workspace.resolve_files(db, storage_keys, owner_id=owner_id)
        except Exception as exc:
            return {"loaded": [], **_fail("load_files", exc)}
        return {"loaded": entries}

    async def write_file(name: str, content: str, append: bool = False) -> dict[str, Any]:
        """在工作区写一个文本文件。

        Args:
            name: 相对工作区根的文件名，比如 report.md。
            content: 本次要写入的文本。一次不要写太长（建议不超过约 200 行或 8KB），
                长文件分段写，避免工具参数的 JSON 被截断或转义出错。
            append: 默认 false 覆盖写入；分段写时第一段用 false，之后每段用 true 追加。
                追加要求文件已存在；请按顺序逐段调用，不要并行 append。
        """
        try:
            result = await workspace.put_file(name, content, append=append)
        except Exception as exc:
            return _fail("write_file", exc)
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
            return _fail("read_file", exc)
        return result

    async def list_files(subdir: str = ".") -> dict[str, Any]:
        """列工作区某个目录的直接子项。

        Args:
            subdir: 相对工作区根的目录，默认根目录。
        """
        try:
            result = await workspace.list_files(subdir)
        except Exception as exc:
            return _fail("list_files", exc)
        return result

    async def publish_file(ctx: RunContext[Any], path: str) -> dict[str, Any]:
        """把工作区里的文件上传到云端存储，用户即可在页面上直接下载。

        Args:
            path: 相对工作区根的文件路径，比如 report.pdf 或 out/chart.png。
        """
        store = workspace.storage
        if store is None:
            return {"error": "对象存储未启用，无法发布文件"}
        try:
            data = await workspace.read_binary(path, max_bytes=settings.max_upload_bytes)
        except Exception as exc:
            return _fail("publish_file", exc)
        name = PurePosixPath(str(path).replace("\\", "/")).name or "file"
        try:
            async with factory() as db:
                # 类型交给 direct_upload 统一探测；入库后 FileRecord 就是唯一权威
                record = await file_service.direct_upload(
                    db, settings, store, owner_id, name, None, data
                )
        except Exception as exc:
            return _fail("publish_file", exc)
        media_type = effective_media_type(record.name, record.content_type)
        # 产物卡片由工具直接推给前端；ResourceItem 由 turn 从事件落库
        await ctx.emit(
            ArtifactEvent(
                media=[
                    ArtifactMedia(
                        file_id=str(record.id),
                        name=record.name,
                        media_type=media_type,
                        size=record.size,
                    )
                ]
            )
        )
        return {
            "file_id": str(record.id),
            "name": record.name,
            "size": record.size,
            "media_type": media_type,
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
                return _fail("run_command", exc)
            return result

        tools.append(Tool(run_command))
    return tools


def _fail(tool_name: str, exc: Exception) -> dict[str, Any]:
    """工具失败不打断整轮：日志要能定位到是哪个工具，回给模型的只留可读原因。

    预期内的 WorkspaceError 用原话（本来就是写给用户看的），
    其余带上类型名并截断，避免把上游长篇响应体灌进模型上下文。
    """
    logger.error("Workspace tool %s failed", tool_name, exc_info=exc)
    detail = describe_error(exc, include_type=not isinstance(exc, WorkspaceError))
    return {"error": detail}


def workspace_instructions(
    *, include_workspace: bool = True, include_read_image: bool = True
) -> str:
    """提示词里的资源约定段；只描述本轮真正挂载的工具，避免说明和工具对不上。"""
    if not include_workspace and not include_read_image:
        return ""
    parts = [
        "## 文件资源\n"
        "会话里的文件、图片和视频都以 "
        '<resource storage_key=".." original_name=".." mime_type=".."/> 表示：'
        "storage_key 是取用凭据，也是文件记录的 file_id；original_name 是给用户的文件名。"
    ]
    if include_read_image:
        parts.append(
            "用户直接上传的图片已经能看见；其他图片（工具产物、工作区文件）用 read_image 读取，"
            "传 file_id（resource 标签里的 storage_key）或工作区相对路径，不要用 read_file 读图片。"
        )
    if include_workspace:
        parts.append(
            "要把文件（含图片/视频）落进本轮工作区处理，"
            "先调 load_files（把 storage_key 传进去），"
            "它会以 original_name 落进工作区，之后的 write_file / read_file 都用相对路径。"
            "工作区里的文件不会自动出现在会话里；只有调用 publish_file 才会上传成可下载的产物，"
            "所以需要交付的文件要主动发布。需要看文本内容时用 read_file 范围读取。"
            "写长文件（超过约 200 行或 8KB）不要一次性塞进一个 write_file："
            "先写第一段（append=false），再按顺序用 append=true 逐段追加，避免长 JSON 参数被截断。"
        )
    parts.append("回答正文不要回显 <resource/> 标签，直接说文件名即可。")
    return "".join(parts)
