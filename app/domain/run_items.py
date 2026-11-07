"""run.content 的类型化事件项。

run 是树节点；content 按发生顺序存 item。BaseItem 的两个开关分别控制
「是否拼进模型上下文」和「是否在前端展示」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.file_ref import FileIdRef, FileRef
from app.domain.time import now_utc
from app.enums import ItemType

USAGE_FIELDS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
)


class TokenUsage(BaseModel):
    """一次 run 或一次压缩产生的 token 用量。"""

    model_config = ConfigDict(extra="ignore")

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def _fill_total(self) -> Self:
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens
        return self

    def has_values(self) -> bool:
        return any(getattr(self, field) for field in USAGE_FIELDS)

    def merged(self, other: TokenUsage) -> TokenUsage:
        data = self.model_dump()
        for field in USAGE_FIELDS:
            data[field] = getattr(self, field) + getattr(other, field)
        return TokenUsage.model_validate(data)

    def subtract(self, other: TokenUsage) -> TokenUsage:
        """扣掉已经结算过的部分（结算幂等用）；不会出现负数。"""
        data = self.model_dump()
        for field in USAGE_FIELDS:
            data[field] = max(getattr(self, field) - getattr(other, field), 0)
        return TokenUsage.model_validate(data)


class PendingInterrupt(BaseModel):
    """run 里一个等待 resume 的工具调用；工具参数仍在 ToolCallItem 上。"""

    interrupt_id: UUID
    tool_call_id: str
    kind: Literal["call", "approval"]


class BaseItem(BaseModel):
    """所有事件的公共头。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    # 是否参与上下文拼接
    in_context: bool = True
    # 是否在前端展示
    display: bool = True
    created_at: datetime = Field(default_factory=now_utc)


class TextItem(BaseItem):
    type: Literal[ItemType.TEXT] = ItemType.TEXT
    role: Literal["user", "assistant", "system"] = "assistant"
    text: str = ""
    part_id: str | None = None
    provider_name: str | None = None
    provider_details: dict[str, Any] | None = None


class FileMediaItem(BaseItem):
    """图片/视频/文件共用的引用头：只存对象存储引用，不存字节。"""

    file_id: FileIdRef
    name: str = "file"
    media_type: str = "application/octet-stream"
    size: int = 0


class ImageItem(FileMediaItem):
    type: Literal[ItemType.IMAGE] = ItemType.IMAGE
    role: Literal["user", "assistant"] = "user"
    # 画面描述（生成图就是 prompt）；文件名在 name
    alt: str | None = None


class VideoItem(FileMediaItem):
    type: Literal[ItemType.VIDEO] = ItemType.VIDEO
    role: Literal["user", "assistant"] = "user"
    alt: str | None = None


class ResourceItem(FileMediaItem):
    """指向对象存储里一个文件的引用，本体不进消息：模型按 file_id 取用。"""

    type: Literal[ItemType.RESOURCE] = ItemType.RESOURCE
    role: Literal["user", "assistant"] = "user"


class ThinkingItem(BaseItem):
    type: Literal[ItemType.THINKING] = ItemType.THINKING
    text: str = ""
    part_id: str | None = None
    signature: str | None = None
    provider_name: str | None = None
    provider_details: dict[str, Any] | None = None


class ToolCallItem(BaseItem):
    type: Literal[ItemType.TOOL_CALL] = ItemType.TOOL_CALL
    tool_call_id: str
    tool_name: str
    args: Any = None
    part_id: str | None = None
    provider_name: str | None = None
    provider_details: dict[str, Any] | None = None


class ToolResultItem(BaseItem):
    type: Literal[ItemType.TOOL_RESULT] = ItemType.TOOL_RESULT
    tool_call_id: str
    tool_name: str
    content: Any = None
    outcome: Literal["success", "failed", "denied", "interrupted", "retried"] = "success"
    metadata: Any = None
    # 工具结果里被剥出的媒体引用；回放时按 file_id 取回字节
    media: list[FileRef] = Field(default_factory=list)


class ErrorItem(BaseItem):
    type: Literal[ItemType.ERROR] = ItemType.ERROR
    code: str
    message: str
    provider: str | None = None
    retryable: bool = False

    def __init__(self, **data: Any) -> None:
        data.setdefault("in_context", False)
        super().__init__(**data)


class ApprovalRequestItem(BaseItem):
    """一批需要人工审批的 tool call；参数仍在对应的 ToolCallItem 上。"""

    type: Literal[ItemType.APPROVAL_REQUEST] = ItemType.APPROVAL_REQUEST
    interrupt_id: UUID
    tool_call_ids: list[str] = Field(min_length=1)

    def __init__(self, **data: Any) -> None:
        data.setdefault("in_context", False)
        data.setdefault("display", False)
        super().__init__(**data)


class CallRequestItem(BaseItem):
    """一批委托给外部执行方的 tool call。"""

    type: Literal[ItemType.CALL_REQUEST] = ItemType.CALL_REQUEST
    interrupt_id: UUID
    tool_call_ids: list[str] = Field(min_length=1)
    # tool_call_id -> CallDeferred 的 metadata
    metadata: dict[str, Any] | None = None

    def __init__(self, **data: Any) -> None:
        data.setdefault("in_context", False)
        data.setdefault("display", False)
        super().__init__(**data)


class CompactionItem(BaseItem):
    """把一段历史折叠成的摘要；它本身是后续上下文重建的起点。

    压缩结果写在目标 run 的 content 开头，并同步标记 run.compacted；
    build_context 自底向上找到最近的标记后，从这里往后取 Item。
    """

    type: Literal[ItemType.COMPACTION] = ItemType.COMPACTION
    summary: str = Field(min_length=1)
    # 被摘要覆盖的历史上下文估算 token 数
    tokens_before: int = Field(default=0, ge=0)
    # 被摘要覆盖的 Item 数
    items_compacted: int = Field(default=0, ge=0)


class CustomItem(BaseItem):
    """只给 UI 的卡片；不参与模型上下文。"""

    type: Literal[ItemType.CUSTOM] = ItemType.CUSTOM
    renderer: str
    version: int = 1
    data: Any = None
    key: str | None = None

    def __init__(self, **data: Any) -> None:
        data.setdefault("in_context", False)
        super().__init__(**data)


RunItem = Annotated[
    TextItem
    | ImageItem
    | VideoItem
    | ResourceItem
    | ThinkingItem
    | ToolCallItem
    | ToolResultItem
    | ErrorItem
    | ApprovalRequestItem
    | CallRequestItem
    | CompactionItem
    | CustomItem,
    Field(discriminator="type"),
]

PendingInterrupts = list[PendingInterrupt]


def resource_tag(file_id: str, name: str, media_type: str) -> str:
    """resource 在上下文里的文本形状；storage_key 只作为该协议的属性名。"""
    return f'<resource storage_key="{file_id}" original_name="{name}" mime_type="{media_type}"/>'


def item_text(item: RunItem) -> str:
    """检索 / 分支预览用文本；图片视频只留占位。"""
    if isinstance(item, TextItem):
        return item.text
    if isinstance(item, (ImageItem, VideoItem)):
        return item.alt or item.name or ("[图片]" if isinstance(item, ImageItem) else "[视频]")
    if isinstance(item, ResourceItem):
        return item.name
    if isinstance(item, ThinkingItem):
        return item.text
    if isinstance(item, ToolCallItem):
        return item.tool_name
    if isinstance(item, ToolResultItem):
        return str(item.content) if item.content is not None else ""
    if isinstance(item, ErrorItem):
        return f"{item.code} {item.message}"
    if isinstance(item, CompactionItem):
        return item.summary
    return ""
