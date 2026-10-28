"""浏览器声明工具的转换。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, ExternalToolset

from app.schemas.run import FrontendTool


def frontend_toolset(tools: Sequence[FrontendTool]) -> AbstractToolset[Any] | None:
    """把浏览器声明的工具变成外部 toolset。

    外部工具在服务端没有实现，模型调用后会被收进 DeferredToolRequests.calls，
    也就是前端的 Call 中断；不需要为每个前端工具在后端补一份样板。
    """
    if not tools:
        return None
    return ExternalToolset(
        [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
    )
