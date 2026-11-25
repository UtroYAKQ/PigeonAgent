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

_MAX_PUBLISH_BATCH = 10


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
            content: 本次要写入的文本。单次建议不超过约 24KB；更长的内容优先用脚本生成，
                避免工具参数的 JSON 被截断或转义出错。
            append: 默认 false 覆盖写入；分段写时第一段用 false，之后每段用 true 追加。
                追加在沙箱里就地完成，只上传新增内容；请按顺序逐段调用，不要并行 append。
        """
        try:
            result = await workspace.put_file(name, content, append=append)
        except Exception as exc:
            return _fail("write_file", exc)
        return result

    async def read_file(name: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
        """按行范围读工作区里的文本文件，带行号；只读，改文件用 write_file。

        大文件在沙箱里只取目标行，不会整份下载；找内容优先用 grep_files 定位。

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

    async def list_files(
        subdir: str = ".", pattern: str | None = None, recursive: bool = False
    ) -> dict[str, Any]:
        """列工作区里的文件与目录；递归或通配符一次列全，别逐层多次调用。

        Args:
            subdir: 相对工作区根的目录，默认根目录。
            pattern: 文件名通配符，比如 *.py；留空列全部。
            recursive: 是否递归到子目录，默认 false 只列直接子项。
        """
        try:
            result = await workspace.list_files(subdir, pattern=pattern, recursive=recursive)
        except Exception as exc:
            return _fail("list_files", exc)
        return result

    async def grep_files(
        pattern: str,
        subdir: str = ".",
        glob: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """按正则检索工作区文本，返回命中的路径、行号和行内容；找内容先用它定位。

        Args:
            pattern: 正则表达式（grep -E 语义），比如 "TODO|FIXME"。
            subdir: 相对工作区根的目录，默认根目录。
            glob: 只检索匹配该通配符的文件，比如 *.py；留空检索全部文本文件。
            max_results: 最多返回多少条命中，1~50，默认 50。
        """
        try:
            result = await workspace.grep_files(pattern, subdir, glob, max_results=max_results)
        except Exception as exc:
            return _fail("grep_files", exc)
        return result

    async def publish_file(ctx: RunContext[Any], paths: list[str]) -> dict[str, Any]:
        """把工作区里的文件上传到云端存储，用户即可在页面上直接下载。

        Args:
            paths: 相对工作区根的文件路径列表，一次最多 10 个，比如
                ["report.pdf", "out/chart.png"]。
        """
        store = workspace.storage
        if store is None:
            return {"error": "对象存储未启用，无法发布文件"}
        wanted = [str(path).strip() for path in paths if str(path).strip()]
        if not wanted:
            return {"error": "paths 不能为空"}
        published: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        media: list[ArtifactMedia] = []
        for path in wanted[:_MAX_PUBLISH_BATCH]:
            try:
                data = await workspace.read_binary(path, max_bytes=settings.max_upload_bytes)
            except Exception as exc:
                failed.append({"path": path, **_fail("publish_file", exc)})
                continue
            name = PurePosixPath(path.replace("\\", "/")).name or "file"
            try:
                async with factory() as db:
                    # 类型交给 direct_upload 统一探测；入库后 FileRecord 就是唯一权威
                    record = await file_service.direct_upload(
                        db, settings, store, owner_id, name, None, data
                    )
            except Exception as exc:
                failed.append({"path": path, **_fail("publish_file", exc)})
                continue
            media_type = effective_media_type(record.name, record.content_type)
            published.append(
                {
                    "path": path,
                    "file_id": str(record.id),
                    "name": record.name,
                    "size": record.size,
                    "media_type": media_type,
                }
            )
            media.append(
                ArtifactMedia(
                    file_id=str(record.id),
                    name=record.name,
                    media_type=media_type,
                    size=record.size,
                )
            )
        # 产物卡片由工具直接推给前端；ResourceItem 由 turn 从事件落库
        if media:
            await ctx.emit(ArtifactEvent(media=media))
        result: dict[str, Any] = {"published": published, "failed": failed}
        if len(wanted) > _MAX_PUBLISH_BATCH:
            result["note"] = f"一次最多发布 {_MAX_PUBLISH_BATCH} 个文件，多出的已忽略"
        return result

    tools = [
        Tool(load_files),
        Tool(write_file),
        Tool(read_file),
        Tool(list_files),
        Tool(grep_files),
        Tool(publish_file),
    ]
    if isinstance(workspace, SandboxWorkspace):

        async def run_command(command: str, timeout_seconds: int = 120) -> dict[str, Any]:
            """在沙箱里跑一条 Linux 命令，返回 stdout/stderr/exit_code。

            多步文件处理优先用一条命令完成，别拆成很多次 read/write/list。

            Args:
                command: 要执行的命令，在本轮工作区目录里执行。
                timeout_seconds: 最长执行秒数，默认 120。
            """
            try:
                result = await workspace.run_command(command, timeout_seconds)
            except Exception as exc:
                return _fail("run_command", exc)
            return result

        async def run_script(code: str, timeout_seconds: int = 120) -> dict[str, Any]:
            """在工作区里用 Python 一次完成批量或长文件操作（生成、转换、统计）。

            比多次 write_file/read_file 往返快得多；脚本以 python3 -c 同步执行。

            Args:
                code: 完整 Python 代码；用相对路径读写工作区文件，比如 Path("report.md")。
                timeout_seconds: 最长执行秒数，默认 120。
            """
            try:
                result = await workspace.run_script(code, timeout_seconds)
            except Exception as exc:
                return _fail("run_script", exc)
            return result

        tools.extend([Tool(run_command), Tool(run_script)])
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
    *,
    include_workspace: bool = True,
    include_read_image: bool = True,
    include_run_tools: bool = False,
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
        guidance = (
            "要把文件（含图片/视频）落进本轮工作区处理，"
            "先调 load_files（把 storage_key 传进去），"
            "它会以 original_name 落进工作区，之后的 write_file / read_file 都用相对路径。"
            "工作区里的文件不会自动出现在会话里；只有调用 publish_file 才会上传成可下载的产物，"
            "需要交付的文件要主动发布（一次可以传多个路径）。"
            "找内容先用 grep_files 定位，不要逐个 read_file 盲找；"
            "list_files 支持 pattern 和 recursive，别逐层多次列目录。"
        )
        if include_run_tools:
            guidance += (
                "多步或批量文件处理优先用一条 run_command / run_script 完成，别拆成很多次小调用；"
                "生成很长的文件也优先用 run_script 一次写盘。"
            )
        guidance += (
            "需要分段写长文件时，单次建议不超过约 24KB："
            "第一段 append=false，之后按顺序 append=true，追加会就地完成、只传新增内容。"
        )
        parts.append(guidance)
    parts.append("回答正文不要回显 <resource/> 标签，直接说文件名即可。")
    return "".join(parts)
