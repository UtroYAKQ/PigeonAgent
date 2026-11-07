"""本轮工具总装：工具、能力判断和对应提示词只在这里出一次。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai import Tool
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.tools.image import make_generate_image, make_read_image
from app.agents.tools.web import web_search_tools
from app.agents.tools.workspace import workspace_instructions, workspace_tools
from app.core.config import Settings
from app.sandbox.workspace import RunWorkspace


@dataclass(frozen=True, slots=True)
class ToolBundle:
    tools: list[Tool[Any]]
    instructions: str | None


def build_tool_bundle(
    model: Model,
    *,
    workspace: RunWorkspace | None,
    session_factory: async_sessionmaker[AsyncSession],
    owner_id: UUID | None,
    settings: Settings,
    run_id: UUID | None,
    image_model_id: int | None,
    enable_image_generation: bool,
    enable_web_search: bool,
    offer_workspace_tools: bool,
) -> ToolBundle:
    tools: list[Tool[Any]] = []
    has_workspace_tools = workspace is not None and offer_workspace_tools
    can_read_image = False
    can_generate_image = False
    if workspace is not None:
        if offer_workspace_tools:
            tools.extend(
                workspace_tools(workspace, session_factory, owner_id=owner_id, settings=settings)
            )
        storage = workspace.storage
        if storage is not None:
            can_read_image = (offer_workspace_tools or enable_image_generation) and bool(
                model.profile.get("supports_image_input", True)
            )
            if can_read_image:
                tools.append(
                    Tool(
                        make_read_image(
                            session_factory,
                            owner_id=owner_id,
                            settings=settings,
                            storage=storage,
                            workspace=workspace,
                        )
                    )
                )
            can_generate_image = enable_image_generation and image_model_id is not None
            if can_generate_image:
                tools.append(
                    Tool(
                        make_generate_image(
                            session_factory,
                            owner_id=owner_id,
                            settings=settings,
                            run_id=run_id,
                            image_model_id=image_model_id,
                        )
                    )
                )

    if enable_web_search:
        tools.extend(web_search_tools(settings))

    instructions = (
        workspace_instructions(
            include_workspace=has_workspace_tools,
            include_read_image=can_read_image,
        )
        or None
    )
    return ToolBundle(tools=tools, instructions=instructions)
