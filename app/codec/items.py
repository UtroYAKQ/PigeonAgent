"""ModelMessage / ToolReturnPart 到类型化 RunItem 的转换。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    SpeechPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.codec.content import content_to_json, has_failure_report, to_json_value
from app.domain.media.file_ref import TOOL_MEDIA_METADATA_KEY, FileRef
from app.domain.run_items import (
    ImageItem,
    ResourceItem,
    RunItem,
    TextItem,
    ThinkingItem,
    ToolCallItem,
    ToolResultItem,
    VideoItem,
)
from app.schemas.run import Attachment


def attachment_items(attachments: Sequence[Attachment]) -> list[RunItem]:
    items: list[RunItem] = []
    for attachment in attachments:
        if attachment.kind == "image":
            items.append(
                ImageItem(
                    role="user",
                    file_id=attachment.file_id,
                    name=attachment.name,
                    media_type=attachment.media_type,
                    alt=attachment.name,
                )
            )
        else:
            items.append(
                VideoItem(
                    role="user",
                    file_id=attachment.file_id,
                    name=attachment.name,
                    media_type=attachment.media_type,
                    alt=attachment.name,
                )
            )
    return items


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
                args=to_json_value(part.args),
                part_id=part.id,
                provider_name=part.provider_name,
                provider_details=part.provider_details,
            )
        ]
    # 模型原生二进制只能展示、没有 file_id；统一媒体模型不再落 base64
    if isinstance(part, SpeechPart):
        if not part.transcript:
            return []
        return [
            TextItem(
                role="assistant",
                text=part.transcript,
                part_id=part.id,
                provider_name=part.provider_name,
                provider_details=part.provider_details,
            )
        ]
    return []


def tool_result_item(part: ToolReturnPart | RetryPromptPart) -> ToolResultItem:
    if isinstance(part, RetryPromptPart):
        return ToolResultItem(
            tool_call_id=part.tool_call_id,
            tool_name=part.tool_name or "tool",
            content=content_to_json(part.content),
            outcome="retried",
        )
    outcome = part.outcome
    if outcome == "success" and has_failure_report(part.content):
        outcome = "failed"
    metadata = part.metadata
    media: list[FileRef] = []
    if isinstance(metadata, dict):
        raw_media = metadata.get(TOOL_MEDIA_METADATA_KEY)
        if isinstance(raw_media, list):
            for entry in raw_media:
                try:
                    media.append(FileRef.model_validate(entry))
                except ValueError:
                    continue
            metadata = {
                key: value for key, value in metadata.items() if key != TOOL_MEDIA_METADATA_KEY
            } or None
    return ToolResultItem(
        tool_call_id=part.tool_call_id,
        tool_name=part.tool_name,
        content=content_to_json(part.content),
        outcome=outcome,
        metadata=to_json_value(metadata),
        media=media,
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
            # 没有 file_id 的 URL/base64 无法回放成统一媒体 item，导入时直接忽略
            items.extend(
                TextItem(role="user", text=element)
                for element in content
                if isinstance(element, str)
            )
        elif isinstance(request_part, SystemPromptPart):
            items.append(TextItem(role="system", text=request_part.content))
        elif isinstance(request_part, (ToolReturnPart, RetryPromptPart)):
            items.append(tool_result_item(request_part))
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
