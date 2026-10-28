"""run.content <-> Pydantic AI ModelMessage 的编解码。

持久化只存类型化 item；重建上下文时按 item 顺序和角色重新分组：
连续的 request 侧 item 合成 ModelRequest，连续的 response 侧 item 合成 ModelResponse。
"""

from __future__ import annotations

import base64
import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic_ai import DeferredToolRequests, RunUsage
from pydantic_ai.messages import (
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    FilePart,
    FileUrl,
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SpeechPart,
    SystemPromptPart,
    TextContent,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.usage import RequestUsage

from app.schemas.run import Attachment
from app.schemas.run_item import (
    ApprovalRequestItem,
    CallRequestItem,
    FileItem,
    ImageItem,
    ResourceItem,
    RunItem,
    TextItem,
    ThinkingItem,
    TokenUsage,
    ToolCallItem,
    ToolResultItem,
    VideoItem,
    item_text,
    resource_tag,
)


def _coerce_json(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _coerce_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if hasattr(value, "model_dump"):
        return _coerce_json(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _coerce_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def jsonable(value: Any) -> Any:
    """把 dataclass / pydantic 模型 / 普通值转成可 JSON 序列化的结构。"""
    return json.loads(json.dumps(_coerce_json(value), ensure_ascii=False))


_URL_BY_KIND: dict[str, type[FileUrl]] = {
    "image-url": ImageUrl,
    "video-url": VideoUrl,
    "audio-url": AudioUrl,
    "document-url": DocumentUrl,
}


def content_to_json(content: Any) -> Any:
    """模型/工具内容转成可存储且能还原的结构。

    bytes 直接走 jsonable 会变成 ``b'\\x89...'`` 字符串，回放上下文时图就废了，
    所以媒体单独打标成 media 结构。
    """
    if content is None or isinstance(content, (str, int, float, bool)):
        return content
    if isinstance(content, BinaryContent):
        return {
            "media": "binary",
            "media_type": str(content.media_type),
            "data": base64.b64encode(content.data).decode("ascii"),
        }
    if isinstance(content, FileUrl):
        for kind, url_type in _URL_BY_KIND.items():
            if isinstance(content, url_type):
                return {"media": kind, "url": content.url}
        return {"media": "document-url", "url": content.url}
    if isinstance(content, TextContent):
        return content.content
    if isinstance(content, Sequence):
        return [content_to_json(element) for element in content]
    return jsonable(content)


def content_from_json(value: Any) -> Any:
    """``content_to_json`` 的逆变换；没有 media 标记的老数据原样返回。"""
    if isinstance(value, list):
        return [content_from_json(element) for element in value]
    if isinstance(value, dict):
        kind = value.get("media")
        if kind == "binary":
            return BinaryContent(
                data=base64.b64decode(value["data"]), media_type=value["media_type"]
            )
        url_type = _URL_BY_KIND.get(kind) if isinstance(kind, str) else None
        if url_type is not None:
            return url_type(url=value["url"])
    return value


def usage_delta(total: TokenUsage, prior: TokenUsage | None) -> TokenUsage:
    """AgentRunResult.usage 含历史 seed，本 run 只记差值。"""
    if prior is None:
        return total
    data = {
        field: max(0, getattr(total, field) - getattr(prior, field))
        for field in (
            "requests",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    }
    data["total_tokens"] = data["input_tokens"] + data["output_tokens"]
    return TokenUsage.model_validate(data)


def token_usage(usage: Any) -> TokenUsage | None:
    if usage is None:
        return None
    dotted = jsonable(usage)
    if not isinstance(dotted, dict):
        return None
    converted = TokenUsage.model_validate(
        {key: value for key, value in dotted.items() if value is not None}
    )
    if converted.has_values() and not converted.requests:
        converted.requests = 1
    return converted if converted.has_values() else None


def _user_content(item: RunItem, media: Mapping[str, tuple[bytes, str]] | None = None) -> Any:
    if isinstance(item, TextItem):
        return item.text
    if isinstance(item, ResourceItem):
        return resource_tag(item.storage_key, item.name, item.media_type)
    if isinstance(item, (ImageItem, VideoItem)):
        if not item.file_id:
            return None
        is_image = isinstance(item, ImageItem)
        media_type = item.media_type or ("image/png" if is_image else "video/mp4")
        name = item.alt or ("image" if is_image else "video")
        # 标签给模型一个可引用的 storage_key；字节随消息内联，模型直接看得到内容
        tag = resource_tag(item.file_id, name, media_type)
        entry = (media or {}).get(item.file_id)
        if entry is None:
            return tag
        return [tag, BinaryContent(data=entry[0], media_type=entry[1])]
    return None


def _tool_return_part(item: ToolResultItem) -> ToolReturnPart | RetryPromptPart:
    content = content_from_json(item.content)
    if item.outcome == "retried":
        return RetryPromptPart(
            content=content if isinstance(content, (str, list)) else str(content),
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
        )
    return ToolReturnPart(
        tool_name=item.tool_name,
        tool_call_id=item.tool_call_id,
        content=content,
        outcome=item.outcome,
        metadata=item.metadata,
    )


def attachment_items(attachments: Sequence[Attachment]) -> list[RunItem]:
    items: list[RunItem] = []
    for attachment in attachments:
        if attachment.kind == "image":
            items.append(
                ImageItem(
                    role="user",
                    file_id=attachment.file_id,
                    media_type=attachment.media_type,
                    alt=attachment.name,
                )
            )
        else:
            items.append(
                VideoItem(
                    role="user",
                    file_id=attachment.file_id,
                    media_type=attachment.media_type,
                    alt=attachment.name,
                )
            )
    return items


def _binary_items(content: BinaryContent, *, name: str) -> list[RunItem]:
    """模型产出的二进制内容：图片/视频有自己的 item，其余按文件记账，只给 UI 看不进上下文。"""
    media_type = str(content.media_type)
    data = base64.b64encode(content.data).decode("ascii")
    if media_type.startswith("image/"):
        return [
            ImageItem(
                role="assistant", data=data, media_type=media_type, alt=name, in_context=False
            )
        ]
    if media_type.startswith("video/"):
        return [
            VideoItem(
                role="assistant", data=data, media_type=media_type, alt=name, in_context=False
            )
        ]
    return [
        FileItem(
            role="assistant",
            name=name,
            media_type=media_type,
            data=data,
            size=len(content.data),
            in_context=False,
        )
    ]


def items_from_response_part(part: Any) -> list[RunItem]:
    """一个 response part 事件对应一到两条 Item。"""
    if isinstance(part, TextPart):
        return [
            TextItem(
                role="assistant",
                text=part.content,
                part_id=part.id,
                provider_name=part.provider_name,
                provider_details=part.provider_details,
            )
        ]
    if isinstance(part, ThinkingPart):
        return [
            ThinkingItem(
                text=part.content,
                part_id=part.id,
                signature=part.signature,
                provider_name=part.provider_name,
                provider_details=part.provider_details,
            )
        ]
    if isinstance(part, ToolCallPart):
        return [
            ToolCallItem(
                tool_call_id=part.tool_call_id,
                tool_name=part.tool_name,
                args=jsonable(part.args),
                part_id=part.id,
                provider_name=part.provider_name,
                provider_details=part.provider_details,
            )
        ]
    if isinstance(part, FilePart):
        return _binary_items(part.content, name=part.id or "file")
    if isinstance(part, SpeechPart):
        items: list[RunItem] = []
        if part.transcript:
            items.append(
                TextItem(
                    role="assistant",
                    text=part.transcript,
                    part_id=part.id,
                    provider_name=part.provider_name,
                    provider_details=part.provider_details,
                )
            )
        if part.audio is not None:
            items.extend(_binary_items(part.audio, name="speech"))
        return items
    return []


def tool_result_item(part: ToolReturnPart | RetryPromptPart) -> ToolResultItem:
    if isinstance(part, RetryPromptPart):
        return ToolResultItem(
            tool_call_id=part.tool_call_id,
            tool_name=part.tool_name or "tool",
            content=content_to_json(part.content),
            outcome="retried",
        )
    return ToolResultItem(
        tool_call_id=part.tool_call_id,
        tool_name=part.tool_name,
        content=content_to_json(part.content),
        outcome=part.outcome,
        metadata=jsonable(part.metadata),
    )


def items_from_message(message: ModelMessage) -> list[RunItem]:
    items: list[RunItem] = []
    if isinstance(message, ModelResponse):
        for part in message.parts:
            items.extend(items_from_response_part(part))
        return items

    for request_part in message.parts:
        if isinstance(request_part, UserPromptPart):
            content = request_part.content
            if isinstance(content, str):
                items.append(TextItem(role="user", text=content))
                continue
            for element in content:
                if isinstance(element, str):
                    items.append(TextItem(role="user", text=element))
                elif isinstance(element, ImageUrl):
                    items.append(ImageItem(role="user", url=element.url))
                elif isinstance(element, VideoUrl):
                    items.append(VideoItem(role="user", url=element.url))
                elif isinstance(element, BinaryContent):
                    encoded = base64.b64encode(element.data).decode("ascii")
                    media_type = str(element.media_type)
                    if media_type.startswith("image/"):
                        items.append(ImageItem(role="user", data=encoded, media_type=media_type))
                    elif media_type.startswith("video/"):
                        items.append(VideoItem(role="user", data=encoded, media_type=media_type))
                    else:
                        items.append(
                            FileItem(
                                role="user",
                                name="file",
                                media_type=media_type,
                                data=encoded,
                                size=len(element.data),
                            )
                        )
        elif isinstance(request_part, SystemPromptPart):
            items.append(TextItem(role="system", text=request_part.content))
        elif isinstance(request_part, (ToolReturnPart, RetryPromptPart)):
            items.append(tool_result_item(request_part))
    return items


class _MessageBuilder:
    def __init__(
        self,
        usage: TokenUsage | None,
        media: Mapping[str, tuple[bytes, str]] | None = None,
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
            isinstance(item, (ToolResultItem, ResourceItem))
            or (isinstance(item, TextItem) and item.role in {"user", "system"})
            or (isinstance(item, (ImageItem, VideoItem)) and item.role == "user")
        )
        if is_request:
            if self._side != "request":
                self._flush_response()
                self._side = "request"
            if isinstance(item, ToolResultItem):
                self._flush_user_contents()
                self._request_parts.append(_tool_return_part(item))
            elif isinstance(item, TextItem) and item.role == "system":
                self._flush_user_contents()
                self._request_parts.append(SystemPromptPart(content=item.text))
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
        elif isinstance(item, ResourceItem):
            # 助手侧的产物也用标签回灌：下一轮模型自己看得到它产出过什么文件
            self._response_parts.append(
                TextPart(content=resource_tag(item.storage_key, item.name, item.media_type))
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
    media: Mapping[str, tuple[bytes, str]] | None = None,
) -> list[ModelMessage]:
    builder = _MessageBuilder(usage, media)
    for item in items:
        builder.add(item)
    builder.flush()
    return builder.messages


def sum_usage(messages: Sequence[ModelMessage]) -> RunUsage:
    """把历史里每条 ModelResponse 的 usage 累加回 Conversation，让预算跨轮延续。"""
    usage = RunUsage()
    for message in messages:
        item = getattr(message, "usage", None)
        if item is not None:
            usage += item
            usage.requests += 1
    return usage


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
        tool_parts: list[ToolReturnPart | RetryPromptPart] = []
        for request_part in message.parts:
            if isinstance(request_part, (ToolReturnPart, RetryPromptPart)):
                tool_parts.append(request_part)
        if tool_parts:
            repaired.append(message)
            for tool_part in tool_parts:
                pending.pop(tool_part.tool_call_id, None)
            continue
        flush()
        repaired.append(message)
    flush()
    return repaired


def preview_of(items: Sequence[RunItem]) -> str:
    """反范式预览：只留人和内容相关的部分，base64 和工具参数不进。"""
    chunks: list[str] = []
    for item in items:
        text = item_text(item).strip()
        if text:
            chunks.append(text[:500])
    return " ".join(chunks)[:2000]


def to_request_items(requests: DeferredToolRequests) -> list[RunItem]:
    """一次 DeferredToolRequests 的审批与 Call 共用同一个 interrupt_id，各自成一条批量 item。"""
    batch_id = uuid4()
    items: list[RunItem] = []
    if requests.approvals:
        items.append(
            ApprovalRequestItem(
                interrupt_id=batch_id,
                tool_call_ids=[call.tool_call_id for call in requests.approvals],
            )
        )
    if requests.calls:
        metadata = {
            call_id: value
            for call_id, value in requests.metadata.items()
            if call_id in {call.tool_call_id for call in requests.calls}
        }
        items.append(
            CallRequestItem(
                interrupt_id=batch_id,
                tool_call_ids=[call.tool_call_id for call in requests.calls],
                metadata=metadata or None,
            )
        )
    return items


def user_items_from_text(text: str) -> list[RunItem]:
    return [TextItem(role="user", text=text)]


def copied_user_items(items: Sequence[RunItem]) -> list[RunItem]:
    """重新生成时复制原 run 的用户输入，换新 item id。"""
    copied: list[RunItem] = []
    for item in items:
        if not isinstance(item, (TextItem, ImageItem, VideoItem, ResourceItem)):
            continue
        if item.role != "user" or not item.display:
            continue
        data = item.model_dump()
        data["id"] = uuid4()
        data["created_at"] = datetime.now(UTC)
        copied.append(type(item).model_validate(data))
    return copied
