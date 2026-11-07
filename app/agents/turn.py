"""一轮对话：加载历史、驱动原生事件流，并在这一层把事件落成 item。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any, ClassVar
from uuid import UUID

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    AgentStreamEvent,
    CancellationToken,
    DeferredToolResults,
    PartDeltaEvent,
    PartStartEvent,
    UsageLimits,
)
from pydantic_ai.exceptions import (
    RunCancelled,
)
from pydantic_ai.messages import (
    CustomEvent,
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
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import RunUsage

from app import codec
from app.agents.compaction import estimate_tokens, summarize
from app.agents.errors import summarize_error
from app.agents.events import (
    ApprovalRequestEvent,
    ArtifactEvent,
    CallRequestEvent,
    CompactionResultEvent,
    CompactionStartEvent,
    ImageGeneratedEvent,
    RunCancelledEvent,
    RunFailedEvent,
    RunUsageEvent,
    request_events,
)
from app.agents.store import SessionStore
from app.core.config import DEFAULT_COMPACTION_THRESHOLD
from app.domain.file_ref import TOOL_MEDIA_METADATA_KEY
from app.domain.run_items import (
    ApprovalRequestItem,
    CallRequestItem,
    CompactionItem,
    ErrorItem,
    ImageItem,
    ResourceItem,
    RunItem,
    TextItem,
    ThinkingItem,
    TokenUsage,
    ToolCallItem,
)
from app.enums import RunStatus
from app.models.session_run import SessionRun

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
        context_window: int | None = None,
        compaction_threshold: float = DEFAULT_COMPACTION_THRESHOLD,
        request_limit: int = 200,
    ) -> None:
        self._agent = agent
        self._store = store
        self._user_input = user_input
        self._deferred_tool_results = deferred_tool_results
        self._cancellation_token = cancellation_token
        self._toolsets = toolsets
        self._context_window = context_window
        self._compaction_threshold = compaction_threshold
        # pydantic-ai 默认只允许 50 次模型请求，复杂任务会在中途被拦腰截断
        self._request_limit = request_limit
        # 增量累计的半截内容；PartEnd 落库后清掉，剩下的就是取消/报错时要留痕的
        self._partial_text: list[str] = []
        self._partial_thinking: list[str] = []
        self._partial_tools: dict[str, dict[str, str]] = {}
        self._streaming_tool_id: str | None = None
        self._outbox: list[Any] = []
        self._pending = False
        self._has_result = False
        self._prior_usage: TokenUsage | None = None
        self._run_usage: RunUsage | None = None
        self._usage_recorded = False

    async def events(self) -> AsyncIterator[TurnEventType]:
        await self._store.flush()
        self._store.begin_run()
        current = await self._store.ensure_run(self._user_input)
        async for custom_event in self._compaction_events(current):
            await self._handle_record_event(custom_event)
            yield custom_event
        messages = await self._store.load()
        usage = codec.sum_usage(messages)
        self._run_usage = usage
        self._prior_usage = codec.token_usage(usage)
        try:
            async with self._agent.run_stream_events(
                None,
                message_history=messages,
                deferred_tool_results=self._deferred_tool_results,
                conversation_id=str(self._store.session_id),
                run_id=self._store.run_id,
                usage=usage,
                usage_limits=UsageLimits(request_limit=self._request_limit),
                cancellation_token=self._cancellation_token,
                toolsets=self._toolsets,
            ) as run_events:
                async for event in run_events:
                    await self._handle_record_event(event)
                    for custom_event in self._drain_outbox():
                        yield custom_event
                    yield _reported_tool_outcome(event)
            for custom_event in self._drain_outbox():
                yield custom_event
            # 终态只写一次：先判到这三种里的一种，再落库。
            # 先写 COMPLETED 再补写 FAILED 会让订阅者中间看到一个假的成功。
            if self._pending:
                final_status = RunStatus.INTERRUPTED
            elif self._has_result:
                final_status = RunStatus.COMPLETED
            else:
                # 事件流走完了却始终没收到最终结果：这一轮没有产出
                final_status = RunStatus.FAILED
            await self._finish(final_status)

        except (RunCancelled, GeneratorExit, asyncio.CancelledError):
            await self._handle_record_event(RunCancelledEvent())
            await self._record_incomplete_usage()
            await self._finish(RunStatus.CANCELLED)
            raise
        except Exception as exc:
            await self._handle_record_event(RunFailedEvent(error=_error_item(exc)))
            await self._record_incomplete_usage()
            await self._finish(RunStatus.FAILED)
            raise

    async def _compaction_events(self, current: SessionRun) -> AsyncIterator[CustomEvent]:
        """开跑前按上下文窗口判断是否需要压缩；只把已有历史压进摘要，本轮输入保留原样。"""
        window = self._context_window
        if window is None or window <= 0 or current.parent_run_id is None:
            return
        prior = await self._store.load_context(current.parent_run_id)
        # 未决中断必须原样留在上下文里，等 resume 回填结果
        if not prior.messages or prior.pending:
            return
        prior_tokens = estimate_tokens(prior.messages)
        if prior_tokens <= 0:
            return
        current_tokens = estimate_tokens(codec.messages_from_items(current.content))
        projected = prior_tokens + current_tokens
        if projected < window * self._compaction_threshold:
            return
        model = self._agent.model
        if not isinstance(model, Model):
            return
        yield CompactionStartEvent(estimated_tokens=projected, context_window=window)
        try:
            result = await summarize(
                model,
                prior.messages,
                cancellation_token=self._cancellation_token,
            )
        except Exception:
            # 压缩失败不阻塞正常对话；超窗时再交给模型自身的报错兜底
            logger.warning(
                "Context compaction failed for session %s",
                self._store.session_id,
                exc_info=True,
            )
            return
        if not result.summary:
            return
        yield CompactionResultEvent(
            summary=result.summary,
            tokens_before=prior_tokens,
            items_compacted=sum(1 for run in prior.runs for item in run.content if item.in_context),
            usage=result.usage,
        )

    async def _handle_record_event(self, event: Any) -> None:
        """事件落库的分发入口；每种事件的写库逻辑一个方法，AguiRunner 只负责翻译。

        沿 MRO 查表：pydantic-ai 实际发出的是 ToolResultEvent 的子类
        （FunctionToolResultEvent / OutputToolResultEvent），要按 isinstance 语义命中。
        """
        for cls in type(event).__mro__:
            handler = self._RECORD_HANDLERS.get(cls)
            if handler is not None:
                await handler(self, event)
                return

    async def _on_compaction_start(self, event: CompactionStartEvent) -> None:
        """开始标记只进事件流，不落库。"""

    async def _on_compaction_result(self, event: CompactionResultEvent) -> None:
        await self._store.record_compaction(
            CompactionItem(
                summary=event.summary,
                tokens_before=event.tokens_before,
                items_compacted=event.items_compacted,
            ),
            usage=event.usage,
        )

    async def _on_deferred_requests(self, event: DeferredToolRequestsEvent) -> None:
        self._pending = True
        for request_event in request_events(event.requests):
            await self._handle_record_event(request_event)
            self._outbox.append(request_event)

    async def _on_run_result(self, event: AgentRunResultEvent[Any]) -> None:
        self._has_result = True
        # 最终结果事件是权威用量；置位后取消/异常兜底不再重复记账
        self._usage_recorded = True
        total_usage = codec.token_usage(event.result.usage)
        if total_usage is None:
            return
        delta = codec.usage_delta(total_usage, self._prior_usage)
        if delta.has_values():
            usage_event = RunUsageEvent(usage=delta)
            await self._handle_record_event(usage_event)
            self._outbox.append(usage_event)

    async def _record_incomplete_usage(self) -> None:
        """取消或报错时没有最终结果事件，但已完成的模型请求仍要记用量。

        pydantic-ai 会边跑边把每次请求的用量累加进我们传进去的 ``RunUsage``，
        取出来减去历史水位就是本轮已经真实发生的部分。没有新用量时静默跳过。
        """
        if self._usage_recorded or self._run_usage is None:
            return
        total_usage = codec.token_usage(self._run_usage)
        if total_usage is None:
            return
        delta = codec.usage_delta(total_usage, self._prior_usage)
        if not delta.has_values():
            return
        self._usage_recorded = True
        try:
            await self._handle_record_event(RunUsageEvent(usage=delta))
        except Exception:
            # 收尾阶段不能再抛：不然会覆盖原始的取消/失败原因
            logger.warning(
                "Failed to persist incomplete usage for run %s",
                self._store.run_id,
                exc_info=True,
            )

    async def _on_part_start(self, event: PartStartEvent) -> None:
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

    async def _on_part_delta(self, event: PartDeltaEvent) -> None:
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

    async def _on_part_end(self, event: PartEndEvent) -> None:
        items = codec.items_from_response_part(event.part)
        if items:
            await self._store.append_items(items)
        # 完整版已经落库，这一段不再算半截
        if isinstance(event.part, TextPart):
            self._partial_text.clear()
        elif isinstance(event.part, ThinkingPart):
            self._partial_thinking.clear()
        elif isinstance(event.part, ToolCallPart):
            self._partial_tools.pop(event.part.tool_call_id, None)

    async def _on_image_generated(self, event: ImageGeneratedEvent) -> None:
        """出图工具只发事件；ImageItem 的落库仍统一由 turn 负责。"""
        media = event.media
        await self._store.append_items(
            [
                ImageItem(
                    role="assistant",
                    file_id=media.file_id,
                    name=media.name,
                    media_type=media.media_type,
                    size=media.size,
                    alt=media.alt,
                    in_context=False,
                )
            ]
        )
        # 逐张落库，取消或失败时已出的图不会丢
        await self._store.flush()

    async def _on_artifact(self, event: ArtifactEvent) -> None:
        """产物工具只发事件；ResourceItem 的落库仍统一由 turn 负责。"""
        items = [
            ResourceItem(
                role="assistant",
                file_id=media.file_id,
                name=media.name,
                media_type=media.media_type,
                size=media.size,
                in_context=False,
            )
            for media in event.media
            if media.file_id
        ]
        if not items:
            return
        await self._store.append_items(items)
        await self._store.flush()

    async def _on_tool_result(self, event: ToolResultEvent) -> None:
        part = event.part
        # 有引用的媒体先剥原始二进制再建 item，避免先 base64 编码再丢弃
        metadata = getattr(part, "metadata", None)
        if isinstance(metadata, dict) and metadata.get(TOOL_MEDIA_METADATA_KEY):
            part = replace(part, content=codec.without_binary_media(part.content))
        await self._store.append_items([codec.tool_result_item(part)])

    async def _on_approval_request(self, event: ApprovalRequestEvent) -> None:
        await self._store.append_items(
            [
                ApprovalRequestItem(
                    interrupt_id=UUID(event.interrupt_id),
                    tool_call_ids=event.tool_call_ids,
                )
            ]
        )

    async def _on_call_request(self, event: CallRequestEvent) -> None:
        await self._store.append_items(
            [
                CallRequestItem(
                    interrupt_id=UUID(event.interrupt_id),
                    tool_call_ids=event.tool_call_ids,
                    metadata=event.metadata,
                )
            ]
        )

    async def _on_usage(self, event: RunUsageEvent) -> None:
        await self._store.append_items([], usage=event.usage)

    async def _on_run_failed(self, event: RunFailedEvent) -> None:
        await self._store.append_items([*self._partial_items(), event.error])

    async def _on_run_cancelled(self, event: RunCancelledEvent) -> None:
        await self._store.append_items(self._partial_items())

    _RECORD_HANDLERS: ClassVar[dict[type[Any], Callable[[AgentTurn, Any], Awaitable[None]]]] = {
        CompactionStartEvent: _on_compaction_start,
        CompactionResultEvent: _on_compaction_result,
        DeferredToolRequestsEvent: _on_deferred_requests,
        AgentRunResultEvent: _on_run_result,
        PartStartEvent: _on_part_start,
        PartDeltaEvent: _on_part_delta,
        PartEndEvent: _on_part_end,
        ImageGeneratedEvent: _on_image_generated,
        ArtifactEvent: _on_artifact,
        ToolResultEvent: _on_tool_result,
        ApprovalRequestEvent: _on_approval_request,
        CallRequestEvent: _on_call_request,
        RunUsageEvent: _on_usage,
        RunFailedEvent: _on_run_failed,
        RunCancelledEvent: _on_run_cancelled,
    }

    def _partial_items(self) -> list[RunItem]:
        """半截思考和文本留痕并进上下文；工具调用只留痕不进，残缺 args 会被下一轮请求拒收。"""
        items: list[RunItem] = []
        thinking = "".join(self._partial_thinking).strip()
        if thinking:
            items.append(ThinkingItem(text=thinking))
        text = "".join(self._partial_text).strip()
        if text:
            items.append(TextItem(role="assistant", text=text))
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


def _reported_tool_outcome(event: Any) -> Any:
    """上报给前端的工具结果：先剥掉 base64 图片，再把失败体统一标成 failed。"""
    if not isinstance(event, ToolResultEvent):
        return event
    part = event.part
    if isinstance(part.metadata, dict) and part.metadata.get(TOOL_MEDIA_METADATA_KEY):
        content = codec.without_binary_media(part.content)
        if content is not part.content:
            part = replace(part, content=content)
    if part.outcome == "success" and codec.has_failure_report(part.content):
        part = replace(part, outcome="failed")
    return event if part is event.part else replace(event, part=part)


def _error_item(exc: BaseException) -> ErrorItem:
    summary = summarize_error(exc)
    return ErrorItem(
        code=summary.code,
        message=summary.message,
        provider=getattr(exc, "provider_name", None),
        retryable=summary.retryable,
    )
