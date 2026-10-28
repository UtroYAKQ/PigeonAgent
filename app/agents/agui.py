"""agui_events 的翻译层：原生事件流 -> AG-UI 事件，落库交给 AgentTurn。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from ag_ui.core import BaseEvent, RunAgentInput
from pydantic_ai import Agent, CancellationToken, DeferredToolResults
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.ui.ag_ui import AGUIAdapter

from app.agents.store import SessionStore
from app.agents.turn import AgentTurn


class AguiRunner:
    def __init__(self, agent: Agent[Any, Any], store: SessionStore) -> None:
        self._agent = agent
        self._store = store

    def _adapter(self, run_id: str | None) -> AGUIAdapter:
        # 流式转换只用到 run_input 的 thread_id / run_id，用户消息由 AgentTurn 走 message_history。
        # 前端工具也不放这里：它们已经作为 agent toolset 注入到 run_stream_events，
        # 再让 adapter 从 run_input.tools 建一份会重复注册同名工具。
        return AGUIAdapter(
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
        )
        adapter = self._adapter(run_id)

        async for event in adapter.transform_stream(turn.events()):
            yield event
