"""agui_events 的翻译层：原生事件流 -> AG-UI 事件，落库交给 AgentTurn。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from ag_ui.core import BaseEvent, RunAgentInput, RunErrorEvent
from pydantic_ai import Agent, CancellationToken, DeferredToolResults
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.ui.ag_ui import AGUIAdapter, AGUIEventStream

from app.agents.store import SessionStore
from app.agents.turn import AgentTurn, summarize_error
from app.core.config import DEFAULT_COMPACTION_THRESHOLD


class ClassifiedAGUIEventStream(AGUIEventStream[Any, Any]):
    """上游报错先归类再下发，别把供应商的英文原文直接抛给前端。"""

    async def on_error(self, error: Exception) -> AsyncIterator[BaseEvent]:
        self._error = True
        summary = summarize_error(error)
        yield RunErrorEvent(
            message=summary.message,
            code=summary.code,
            timestamp=self._get_timestamp(),
        )


class ClassifiedAGUIAdapter(AGUIAdapter[Any, Any]):
    def build_event_stream(self) -> AGUIEventStream[Any, Any]:
        return ClassifiedAGUIEventStream(
            self.run_input,
            accept=self.accept,
            ag_ui_version=self.ag_ui_version,
            manage_system_prompt=self.manage_system_prompt,
            preserve_file_data=self.preserve_file_data,
        )


class AguiRunner:
    def __init__(
        self,
        agent: Agent[Any, Any],
        store: SessionStore,
        *,
        context_window: int | None = None,
        compaction_threshold: float = DEFAULT_COMPACTION_THRESHOLD,
        request_limit: int = 200,
    ) -> None:
        self._agent = agent
        self._store = store
        self._context_window = context_window
        self._compaction_threshold = compaction_threshold
        self._request_limit = request_limit

    def _adapter(self, run_id: str | None) -> ClassifiedAGUIAdapter:
        # 流式转换只用到 run_input 的 thread_id / run_id，用户消息由 AgentTurn 走 message_history。
        # 前端工具也不放这里：它们已经作为 agent toolset 注入到 run_stream_events，
        # 再让 adapter 从 run_input.tools 建一份会重复注册同名工具。
        return ClassifiedAGUIAdapter(
            self._agent,
            RunAgentInput(
                thread_id=str(self._store.session_id),
                run_id=run_id or str(uuid4()),
                messages=[],
                tools=[],
                context=[],
                forwarded_props={},
            ),
        )

    async def events(
        self,
        user_input: str | None = None,
        *,
        run_id: str | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        cancellation_token: CancellationToken | None = None,
        toolsets: Sequence[AbstractToolset[Any]] | None = None,
    ) -> AsyncIterator[BaseEvent]:
        turn = AgentTurn(
            self._agent,
            self._store,
            user_input,
            deferred_tool_results=deferred_tool_results,
            cancellation_token=cancellation_token,
            toolsets=toolsets,
            context_window=self._context_window,
            compaction_threshold=self._compaction_threshold,
            request_limit=self._request_limit,
        )
        adapter = self._adapter(run_id)

        async for event in adapter.transform_stream(turn.events()):
            yield event
