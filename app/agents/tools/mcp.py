"""把管理员配置的 MCP 服务器装配成每轮可用的 toolset。

MCP 工具就是普通 tool call：加前缀避免撞名，按服务器配置决定是否按需加载、
是否调用前审批；连接失败的服务器只影响它自己的工具，不拖垮整轮 run。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic_ai import RunContext
from pydantic_ai.toolsets import (
    AbstractToolset,
    ApprovalRequiredToolset,
    ToolsetTool,
    WrapperToolset,
)

from app.core.config import Settings
from app.models.ai.mcp import McpServer
from app.services.mcp import build_mcp_toolset

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpSetup:
    """本轮真正可用的 MCP 服务器、对应 toolset 和给模型的目录提示。"""

    servers: list[McpServer]
    toolsets: list[AbstractToolset[Any]]
    instructions: str | None


@dataclass
class _ResilientToolset(WrapperToolset[Any]):
    """连接失败时返回空工具集；下一个 run 会重新尝试连接。"""

    server_slug: str
    _entered: bool = field(default=False, init=False, repr=False)

    async def __aenter__(self) -> Self:
        try:
            await self.wrapped.__aenter__()
            self._entered = True
        except Exception:
            self._entered = False
            logger.warning(
                "MCP server %s failed to connect; skipping its tools for this run",
                self.server_slug,
                exc_info=True,
            )
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        if not self._entered:
            return None
        try:
            return await self.wrapped.__aexit__(*args)
        except Exception:
            logger.warning(
                "MCP server %s failed to disconnect cleanly", self.server_slug, exc_info=True
            )
            return None

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        try:
            return await super().get_tools(ctx)
        except Exception:
            logger.warning(
                "MCP server %s is unavailable; skipping its tools for this run",
                self.server_slug,
                exc_info=True,
            )
            return {}


def build_mcp_setup(servers: list[McpServer], *, settings: Settings) -> McpSetup:
    ready: list[McpServer] = []
    toolsets: list[AbstractToolset[Any]] = []
    for server in servers:
        try:
            base = build_mcp_toolset(server, settings=settings)
        except Exception:
            logger.warning(
                "MCP server %s credentials unavailable; skipping", server.slug, exc_info=True
            )
            continue
        # PrefixedToolset 会再补一个下划线，最终工具名是 mcp_<slug>__<tool>
        toolset: AbstractToolset[Any] = base.prefixed(f"mcp_{server.slug}_")
        if server.defer_loading:
            toolset = toolset.defer_loading()
        if server.requires_approval:
            toolset = ApprovalRequiredToolset(toolset)
        toolsets.append(_ResilientToolset(toolset, server_slug=server.slug))
        ready.append(server)
    return McpSetup(
        servers=ready,
        toolsets=toolsets,
        instructions=build_mcp_instructions(ready),
    )


def build_mcp_instructions(servers: list[McpServer]) -> str | None:
    if not servers:
        return None
    hint = (
        "需要对应能力时，先用 search_tools 查找它们的工具。"
        if any(server.defer_loading for server in servers)
        else "需要时直接调用对应工具。"
    )
    return "\n".join(
        [
            "## MCP 服务器",
            f"本会话启用了以下 MCP 服务器；{hint}",
            *(
                f"- {server.name}（{server.slug}）：{server.description or '未填写说明'}"
                for server in servers
            ),
        ]
    )
