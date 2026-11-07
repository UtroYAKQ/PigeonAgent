"""RunItem 到 Pydantic AI ModelMessage 的重建。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from app.codec.content import content_from_json
from app.domain.run_items import (
    CompactionItem,
    ImageItem,
    ResourceItem,
    RunItem,
    TextItem,
    ThinkingItem,
    TokenUsage,
    ToolCallItem,
    ToolResultItem,
    VideoItem,
    resource_tag,
)

COMPACTION_SUMMARY_INSTRUCTION = (
    "以下是先前对话的压缩摘要，保留了目标、结论、已完成操作与未完成事项。"
)

COMPACTION_SUMMARY_TAG = "compaction_summary"


def compaction_summary_content(summary: str) -> str:
    """压缩摘要以系统提示的形式回灌，既不冒充用户发言，也不会被当成普通历史。"""
    return (
        f"{COMPACTION_SUMMARY_INSTRUCTION}\n"
        f"<{COMPACTION_SUMMARY_TAG}>\n{summary.strip()}\n</{COMPACTION_SUMMARY_TAG}>"
    )


def _user_content(item: RunItem, media: Mapping[str, bytes] | None = None) -> Any:
    if isinstance(item, TextItem):
        return item.text
    if isinstance(item, ResourceItem):
        return resource_tag(item.file_id, item.name, item.media_type)
    if isinstance(item, (ImageItem, VideoItem)):
        # 标签给模型一个可引用的 file_id；字节随消息内联，模型直接看得到内容
        tag = resource_tag(item.file_id, item.name, item.media_type)
        entry = (media or {}).get(item.file_id)
        if entry is None:
            return tag
        return [tag, BinaryContent(data=entry, media_type=item.media_type)]
    return None


def _tool_return_part(
    item: ToolResultItem, media: Mapping[str, bytes] | None = None
) -> ToolReturnPart | RetryPromptPart:
    content = content_from_json(item.content)
    payloads = [
        BinaryContent(data=entry, media_type=ref.media_type)
        for ref in item.media
        if (entry := (media or {}).get(ref.file_id)) is not None
    ]
    if payloads:
        # 落库时剥掉的媒体按 file_id 取回来了；引用文本仍在 content 里
        if isinstance(content, list):
            content = [*content, *payloads]
        elif content is None:
            content = payloads
        else:
            content = [content, *payloads]
    if item.outcome == "retried":
        return RetryPromptPart(
            content=content if isinstance(content, (str, list)) else str(content),
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
        )
    if item.outcome == "failed" and isinstance(content, dict):
        error = content.get("error")
        # 工具内部吞掉异常后返回的 error 字典已经写明原因；在 outcome=failed 时重建上下文
        # 再包一层 {"error": ...} 只会得到转义过的 JSON，直接还原成错误文案。
        if isinstance(error, str) and error.strip():
            content = error
    return ToolReturnPart(
        tool_name=item.tool_name,
        tool_call_id=item.tool_call_id,
        content=content,
        outcome=item.outcome,
        metadata=item.metadata,
    )


class _MessageBuilder:
    def __init__(
        self,
        usage: TokenUsage | None,
        media: Mapping[str, bytes] | None = None,
    ) -> None:
        self.messages: list[ModelMessage] = []
        self.usage = usage
        self.media = media or {}
        self._usage_attached = False
        self._request_parts: list[Any] = []
        self._user_contents: list[Any] = []
        self._response_parts: list[Any] = []
        self._side: str | None = None

    def _flush_user_contents(self) -> None:
        if not self._user_contents:
            return
        # UserPromptPart 只接受 str 或内容序列；单个 BinaryContent 必须保留成 list
        content: Any = (
            self._user_contents[0]
            if len(self._user_contents) == 1 and isinstance(self._user_contents[0], str)
            else list(self._user_contents)
        )
        self._request_parts.append(UserPromptPart(content=content))
        self._user_contents = []

    def _flush_request(self) -> None:
        self._flush_user_contents()
        if not self._request_parts:
            return
        self.messages.append(ModelRequest(parts=list(self._request_parts)))
        self._request_parts = []

    def _flush_response(self) -> None:
        if not self._response_parts:
            return
        usage = None
        if self.usage is not None and not self._usage_attached:
            usage = RequestUsage(
                input_tokens=self.usage.input_tokens,
                output_tokens=self.usage.output_tokens,
                cache_read_tokens=self.usage.cache_read_tokens,
                cache_write_tokens=self.usage.cache_write_tokens,
            )
            self._usage_attached = True
        if usage is None:
            self.messages.append(ModelResponse(parts=list(self._response_parts)))
        else:
            self.messages.append(ModelResponse(parts=list(self._response_parts), usage=usage))
        self._response_parts = []

    def flush(self) -> None:
        self._flush_request()
        self._flush_response()
        self._side = None

    def add(self, item: RunItem) -> None:
        if not item.in_context:
            return
        is_request = (
            isinstance(item, (ToolResultItem, CompactionItem))
            or (isinstance(item, ResourceItem) and item.role == "user")
            or (isinstance(item, TextItem) and item.role in {"user", "system"})
            or (isinstance(item, (ImageItem, VideoItem)) and item.role == "user")
        )
        if is_request:
            if self._side != "request":
                self._flush_response()
                self._side = "request"
            if isinstance(item, ToolResultItem):
                self._flush_user_contents()
                self._request_parts.append(_tool_return_part(item, self.media))
            elif isinstance(item, TextItem) and item.role == "system":
                self._flush_user_contents()
                self._request_parts.append(SystemPromptPart(content=item.text))
            elif isinstance(item, CompactionItem):
                self._flush_user_contents()
                self._request_parts.append(
                    SystemPromptPart(content=compaction_summary_content(item.summary))
                )
            else:
                content = _user_content(item, self.media)
                if isinstance(content, list):
                    self._user_contents.extend(content)
                elif content is not None:
                    self._user_contents.append(content)
            return

        if self._side != "response":
            self._flush_request()
            self._side = "response"
        if isinstance(item, TextItem):
            self._response_parts.append(
                TextPart(
                    content=item.text,
                    id=item.part_id,
                    provider_name=item.provider_name,
                    provider_details=item.provider_details,
                )
            )
        elif isinstance(item, ThinkingItem):
            self._response_parts.append(
                ThinkingPart(
                    content=item.text,
                    id=item.part_id,
                    signature=item.signature,
                    provider_name=item.provider_name,
                    provider_details=item.provider_details,
                )
            )
        elif isinstance(item, ToolCallItem):
            self._response_parts.append(
                ToolCallPart(
                    tool_name=item.tool_name,
                    args=item.args,
                    tool_call_id=item.tool_call_id,
                    id=item.part_id,
                    provider_name=item.provider_name,
                    provider_details=item.provider_details,
                )
            )


def messages_from_items(
    items: Sequence[RunItem],
    *,
    usage: TokenUsage | None = None,
    media: Mapping[str, bytes] | None = None,
) -> list[ModelMessage]:
    builder = _MessageBuilder(usage, media)
    for item in items:
        builder.add(item)
    builder.flush()
    return builder.messages


def repair_dangling_tool_calls(
    messages: Sequence[ModelMessage],
    *,
    skip_tool_call_ids: set[str] | None = None,
) -> list[ModelMessage]:
    """provider 兜底：没有 tool result 的 tool call 补一条错误结果。

    等待 resume 的调用不能补结果，否则 pydantic-ai 会认为它已经执行过。
    """
    skip = skip_tool_call_ids or set()
    repaired: list[ModelMessage] = []
    pending: dict[str, ToolCallPart] = {}

    def flush() -> None:
        if not pending:
            return
        missing = [call for call_id, call in pending.items() if call_id not in skip]
        if missing:
            repaired.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=call.tool_name,
                            tool_call_id=call.tool_call_id,
                            content="No result provided",
                            outcome="failed",
                        )
                        for call in missing
                    ]
                )
            )
        pending.clear()

    for message in messages:
        if isinstance(message, ModelResponse):
            flush()
            repaired.append(message)
            for response_part in message.parts:
                if isinstance(response_part, ToolCallPart):
                    pending[response_part.tool_call_id] = response_part
            continue
        tool_parts = [
            request_part
            for request_part in message.parts
            if isinstance(request_part, (ToolReturnPart, RetryPromptPart))
        ]
        if tool_parts:
            repaired.append(message)
            for tool_part in tool_parts:
                pending.pop(tool_part.tool_call_id, None)
            continue
        flush()
        repaired.append(message)
    flush()
    return repaired
