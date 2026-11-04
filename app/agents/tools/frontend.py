"""浏览器声明工具的转换。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ExternalToolset, ToolsetTool

from app.schemas.run import FrontendTool


class FrontendToolset(ExternalToolset[Any]):
    """外部工具由前端回填结果；给参数修正留几次重试，别让一次截断直接终止整轮。"""

    def __init__(self, tool_defs: list[ToolDefinition], *, max_retries: int = 2) -> None:
        super().__init__(tool_defs)
        self._max_retries = max_retries

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        tools = await super().get_tools(ctx)
        return {name: replace(tool, max_retries=self._max_retries) for name, tool in tools.items()}


def frontend_toolset(tools: Sequence[FrontendTool]) -> AbstractToolset[Any] | None:
    """把浏览器声明的工具变成外部 toolset。

    外部工具在服务端没有实现，模型调用后会被收进 DeferredToolRequests.calls，
    也就是前端的 Call 中断；不需要为每个前端工具在后端补一份样板。
    """
    if not tools:
        return None
    return FrontendToolset(
        [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
    )
