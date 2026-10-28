"""一轮对话：加载历史、驱动原生事件流，并在这一层把事件落成 item。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    AgentStreamEvent,
    CancellationToken,
    DeferredToolResults,
    PartDeltaEvent,
    PartStartEvent,
)
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelConnectionError,
    ModelContextWindowExceededError,
    ModelOverloadedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
    ModelUnavailableError,
    RunCancelled,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    DeferredToolRequestsEvent,
    PartEndEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolResultEvent,
)
from pydantic_ai.toolsets import AbstractToolset

from app.agents.store import SessionStore
from app.enums import RunStatus
from app.events import (
    ApprovalRequestEvent,
    CallRequestEvent,
    RunCancelledEvent,
    RunFailedEvent,
    RunUsageEvent,
    request_events,
)
from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    ErrorItem,
    RunItem,
    TextItem,
    ThinkingItem,
    TokenUsage,
    ToolCallItem,
)
from app.services import item_codec

logger = logging.getLogger(__name__)

type TurnEventType = AgentStreamEvent | AgentRunResultEvent[Any]


class AgentTurn:
    """驱动一轮；所有响应事件的判断和落库都在这里，AguiRunner 只负责翻译。"""

    def __init__(
        self,
        agent: Agent[Any, Any],
        store: SessionStore,
        user_input: str | None,
        *,
        deferred_tool_results: DeferredToolResults | None = None,
        cancellation_token: CancellationToken | None = None,
        toolsets: Sequence[AbstractToolset[Any]] | None = None,
    ) -> None:
        self._agent = agent
        self._store = store
        self._user_input = user_input
        self._deferred_tool_results = deferred_tool_results
        self._cancellation_token = cancellation_token
        self._toolsets = toolsets
        # 增量累计的半截内容；PartEnd 落库后清掉，剩下的就是取消/报错时要留痕的
        self._partial_text: list[str] = []
        self._partial_thinking: list[str] = []
        self._partial_tools: dict[str, dict[str, str]] = {}
        self._streaming_tool_id: str | None = None
        self._outbox: list[Any] = []
        self._pending = False
        self._finished = False
        self._prior_usage: TokenUsage | None = None

    async def events(self) -> AsyncIterator[TurnEventType]:
        self._store.begin_run()
        if self._user_input is not None:
            await self._store.ensure_run(self._user_input)
        messages = await self._store.load()
        usage = item_codec.sum_usage(messages)
        self._prior_usage = item_codec.token_usage(usage)
        try:
            async with self._agent.run_stream_events(
                None,
                message_history=messages,
                deferred_tool_results=self._deferred_tool_results,
                conversation_id=str(self._store.session_id),
                run_id=self._store.run_id,
                usage=usage,
                cancellation_token=self._cancellation_token,
                toolsets=self._toolsets,
            ) as run_events:
                async for event in run_events:
                    await self._handle_record_event(event)
                    for custom_event in self._drain_outbox():
                        yield custom_event
                    yield event
            for custom_event in self._drain_outbox():
                yield custom_event
            await self._finish(RunStatus.INTERRUPTED if self._pending else RunStatus.COMPLETED)
            if not self._pending and not self._finished:
                await self._finish(RunStatus.FAILED)

        except (RunCancelled, GeneratorExit, asyncio.CancelledError):
            await self._handle_record_event(RunCancelledEvent())
            await self._finish(RunStatus.CANCELLED)
            raise
        except Exception as exc:
            await self._handle_record_event(RunFailedEvent(error=_error_item(exc)))
            await self._finish(RunStatus.FAILED)
            raise

    async def _handle_record_event(self, event: Any) -> None:
        """所有事件类型的判断都在这里，AguiRunner 只负责翻译。"""
        if isinstance(event, DeferredToolRequestsEvent):
            self._pending = True
            for request_event in request_events(event.requests):
                await self._handle_record_event(request_event)
                self._outbox.append(request_event)
            return
        if isinstance(event, AgentRunResultEvent):
            self._finished = True
            total_usage = item_codec.token_usage(event.result.usage)
            if total_usage is not None:
                delta = item_codec.usage_delta(total_usage, self._prior_usage)
                if delta.has_values():
                    usage_event = RunUsageEvent(usage=delta)
                    await self._handle_record_event(usage_event)
                    self._outbox.append(usage_event)
            return
        if isinstance(event, PartStartEvent):
            part = event.part
            if isinstance(part, TextPart):
                self._partial_text.append(part.content)
            elif isinstance(part, ThinkingPart):
                self._partial_thinking.append(part.content)
            elif isinstance(part, ToolCallPart):
                self._streaming_tool_id = part.tool_call_id
                self._partial_tools[part.tool_call_id] = {
                    "name": part.tool_name,
                    "args": part.args if isinstance(part.args, str) else "",
                }
            return
        if isinstance(event, PartDeltaEvent):
            part_delta = event.delta
            if isinstance(part_delta, TextPartDelta):
                self._partial_text.append(part_delta.content_delta)
            elif isinstance(part_delta, ThinkingPartDelta):
                self._partial_thinking.append(part_delta.content_delta or "")
            elif isinstance(part_delta, ToolCallPartDelta):
                # 有的 provider 只在开头给 id，后续增量靠它归属
                call_id = part_delta.tool_call_id or self._streaming_tool_id
                if call_id is not None:
                    entry = self._partial_tools.setdefault(call_id, {"name": "", "args": ""})
                    entry["name"] += part_delta.tool_name_delta or ""
                    if isinstance(part_delta.args_delta, str):
                        entry["args"] += part_delta.args_delta
            return
        if isinstance(event, PartEndEvent):
            items = item_codec.items_from_response_part(event.part)
            if items:
                await self._store.append_items(items)
            # 完整版已经落库，这一段不再算半截
            if isinstance(event.part, TextPart):
                self._partial_text.clear()
            elif isinstance(event.part, ThinkingPart):
                self._partial_thinking.clear()
            elif isinstance(event.part, ToolCallPart):
                self._partial_tools.pop(event.part.tool_call_id, None)
            return
        if isinstance(event, ToolResultEvent):
            await self._store.append_items([item_codec.tool_result_item(event.part)])
            return
        if isinstance(event, ApprovalRequestEvent):
            await self._store.append_items(
                [
                    ApprovalRequestItem(
                        interrupt_id=UUID(event.interrupt_id),
                        tool_call_ids=event.tool_call_ids,
                    )
                ]
            )
            return
        if isinstance(event, CallRequestEvent):
            await self._store.append_items(
                [
                    CallRequestItem(
                        interrupt_id=UUID(event.interrupt_id),
                        tool_call_ids=event.tool_call_ids,
                        metadata=event.metadata,
                    )
                ]
            )
            return
        if isinstance(event, RunUsageEvent):
            await self._store.append_items([], usage=event.usage)
            return
        if isinstance(event, RunFailedEvent):
            await self._store.append_items([*self._partial_items(), event.error])
            return
        if isinstance(event, RunCancelledEvent):
            await self._store.append_items(self._partial_items())

    def _partial_items(self) -> list[RunItem]:
        """半截思考、文本和工具调用都留痕，但都不进上下文：残缺 args 会让下一轮请求被拒收。"""
        items: list[RunItem] = []
        thinking = "".join(self._partial_thinking).strip()
        if thinking:
            items.append(ThinkingItem(text=thinking, in_context=False))
        text = "".join(self._partial_text).strip()
        if text:
            items.append(TextItem(role="assistant", text=text, in_context=False))
        for tool_call_id, entry in self._partial_tools.items():
            items.append(
                ToolCallItem(
                    tool_call_id=tool_call_id,
                    tool_name=entry["name"] or "tool",
                    args=entry["args"],
                    in_context=False,
                )
            )
        return items

    def _drain_outbox(self) -> list[Any]:
        events = self._outbox
        self._outbox = []
        return events

    async def _finish(self, status: RunStatus) -> None:
        try:
            await self._store.set_status(status)
        except Exception:
            logger.warning(
                "Failed to set run status %s for session %s",
                status,
                self._store.session_id,
                exc_info=True,
            )


def _error_item(exc: BaseException) -> ErrorItem:
    """按 pydantic-ai 的异常类型判定错误，而不是猜 HTTP 状态码。"""
    code = type(exc).__name__
    message = (str(exc) or code)[:2000]
    retryable = isinstance(exc, RETRYABLE_ERRORS)
    if isinstance(exc, ModelContextWindowExceededError):
        code = "context_window_exceeded"
    elif isinstance(exc, UsageLimitExceeded):
        code = "usage_limit_exceeded"
    elif isinstance(exc, ContentFilterError):
        code = "content_filter"
    return ErrorItem(
        code=code,
        message=message,
        provider=getattr(exc, "provider_name", None),
        retryable=retryable,
    )


RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    ModelConnectionError,
    ModelTimeoutError,
    ModelRateLimitError,
    ModelOverloadedError,
    ModelUnavailableError,
    ModelServerError,
    UnexpectedModelBehavior,
)
