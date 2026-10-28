"""BaseAgent：装配模型、提示词、工具，并把历史、压缩和运行入口收成门面。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar
from uuid import UUID

from ag_ui.core import BaseEvent
from pydantic_ai import (
    Agent,
    AgentCapability,
    AgentRunResult,
    AgentRunResultEvent,
    CancellationToken,
    DeferredToolRequests,
    DeferredToolResults,
    ModelSettings,
    Tool,
)
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.agui import AguiRunner
from app.agents.store import SessionStore
from app.agents.tools import get_current_time, planning_tools
from app.agents.turn import AgentTurn
from app.core.exceptions import ConfigurationError


class BaseAgent:
    """默认父类 agent：装载模型、提示词、工具，自带历史记忆与流式聊天。"""

    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    instructions: ClassVar[str] = ""

    def __init__(
        self,
        model: Model,
        *,
        prompt: str | None = None,
        model_settings: ModelSettings | None = None,
        tools: Sequence[Tool[Any]] = (),
        capabilities: Sequence[AgentCapability[Any]] = (),
        output_type: Any = (str, DeferredToolRequests),
        session: AsyncSession | None = None,
        session_id: UUID | None = None,
        model_id: int | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        run_id: str | None = None,
    ) -> None:
        self._store = (
            SessionStore(
                session,
                session_id,
                model_id,
                session_factory=session_factory,
                run_id=run_id,
            )
            if session is not None and session_id is not None
            else None
        )
        self._agent: Agent[Any, Any] = Agent(
            model,
            name=self.name,
            instructions=self.build_instructions(prompt),
            tools=[*self.default_tools(), *tools],
            model_settings=model_settings,
            capabilities=list(capabilities) or None,
            output_type=output_type,
        )

    # ---------------------------------------------------------------- 装载

    def default_tools(self) -> list[Tool[Any]]:
        return [*planning_tools(), Tool(get_current_time)]

    def build_instructions(self, prompt: str | None) -> str:
        return "\n\n".join(part for part in (self.instructions, prompt) if part)

    # ------------------------------------------------------------ 历史记忆

    def _require_store(self) -> SessionStore:
        if self._store is None:
            raise ConfigurationError("BaseAgent needs session and session_id to use history")
        return self._store

    # ---------------------------------------------------------------- 对话

    async def run(self, user_input: str) -> AgentRunResult[Any]:
        if self._store is None:
            return await self._agent.run(user_input)
        result: AgentRunResult[Any] | None = None
        turn = AgentTurn(self._agent, self._store, user_input)
        async for event in turn.events():
            if isinstance(event, AgentRunResultEvent):
                result = event.result
        if result is None:
            raise RuntimeError("Agent run finished without a result")
        return result

    def agui_events(
        self,
        user_input: str | None = None,
        *,
        run_id: str | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        cancellation_token: CancellationToken | None = None,
        toolsets: Sequence[AbstractToolset[Any]] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        """跑一轮并通过官方 AGUIAdapter 转成 AG-UI 事件；user_input 为 None 表示恢复轮。"""
        runner = AguiRunner(self._agent, self._require_store())
        return runner.events(
            user_input,
            run_id=run_id,
            deferred_tool_results=deferred_tool_results,
            cancellation_token=cancellation_token,
            toolsets=toolsets,
        )
