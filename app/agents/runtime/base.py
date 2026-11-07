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

from app.agents.protocol.agui import AguiRunner
from app.agents.runtime.prompts import BASE_INSTRUCTIONS
from app.agents.runtime.store import SessionStore, UsageObserver
from app.agents.runtime.turn import AgentTurn
from app.agents.tools import get_current_time
from app.core.config import DEFAULT_COMPACTION_THRESHOLD, Settings, get_settings
from app.core.exceptions import ConfigurationError


class BaseAgent:
    """默认父类 agent：装载模型、提示词、工具，自带历史记忆与流式聊天。"""

    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    instructions: ClassVar[str] = BASE_INSTRUCTIONS

    def __init__(
        self,
        model: Model,
        *,
        prompt: str | None = None,
        model_settings: ModelSettings | None = None,
        tools: Sequence[Tool[Any]] = (),
        capabilities: Sequence[AgentCapability[Any]] = (),
        output_type: Any = (str, DeferredToolRequests),
        db: AsyncSession | None = None,
        session_id: UUID | None = None,
        model_id: int | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        run_id: str | None = None,
        context_window: int | None = None,
        compaction_threshold: float = DEFAULT_COMPACTION_THRESHOLD,
        supports_tools: bool = True,
        on_usage: UsageObserver | None = None,
    ) -> None:
        self._settings: Settings = get_settings()
        self._store = (
            SessionStore(
                db,
                session_id,
                model_id,
                session_factory=session_factory,
                run_id=run_id,
                on_usage=on_usage,
            )
            if session_id is not None and (db is not None or session_factory is not None)
            else None
        )
        self._context_window = context_window
        self._compaction_threshold = compaction_threshold
        # 不支持工具的模型连默认工具和 DeferredToolRequests 都不能带
        effective_tools = [*self.default_tools(), *tools] if supports_tools else []
        effective_output = output_type if supports_tools else str
        self._agent: Agent[Any, Any] = Agent(
            model,
            name=self.name,
            instructions=self.build_instructions(prompt),
            tools=effective_tools,
            model_settings=model_settings,
            capabilities=list(capabilities) or None,
            output_type=effective_output,
        )

    # ---------------------------------------------------------------- 装载

    def default_tools(self) -> list[Tool[Any]]:
        # 只留真正与运行时无关的基础工具；文件/图片工具由 run 的 ToolBundle 装配
        return [Tool(get_current_time)]

    def build_instructions(self, prompt: str | None) -> str:
        return "\n\n".join(part for part in (self.instructions, prompt) if part)

    # ------------------------------------------------------------ 历史记忆

    def _require_store(self) -> SessionStore:
        if self._store is None:
            raise ConfigurationError("BaseAgent 需要 db 和 session_id 才能读取历史")
        return self._store

    # ---------------------------------------------------------------- 对话

    async def run(self, user_input: str) -> AgentRunResult[Any]:
        if self._store is None:
            return await self._agent.run(user_input)
        result: AgentRunResult[Any] | None = None
        turn = AgentTurn(
            self._agent,
            self._store,
            user_input,
            context_window=self._context_window,
            compaction_threshold=self._compaction_threshold,
            request_limit=self._settings.agent_request_limit,
        )
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
        runner = AguiRunner(
            self._agent,
            self._require_store(),
            context_window=self._context_window,
            compaction_threshold=self._compaction_threshold,
            request_limit=self._settings.agent_request_limit,
        )
        return runner.events(
            user_input,
            run_id=run_id,
            deferred_tool_results=deferred_tool_results,
            cancellation_token=cancellation_token,
            toolsets=toolsets,
        )
