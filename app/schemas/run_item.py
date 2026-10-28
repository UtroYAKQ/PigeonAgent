"""run.content 的类型化事件项。

run 是树节点；content 按发生顺序存 item。BaseItem 的两个开关分别控制
「是否拼进模型上下文」和「是否在前端展示」。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import ItemType

USAGE_FIELDS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


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


class ImageItem(BaseItem):
    type: Literal[ItemType.IMAGE] = ItemType.IMAGE
    role: Literal["user", "assistant"] = "user"
    url: str | None = None
    # base64；二进制不参与检索列
    data: str | None = None
    # 对象存储引用（= FileRecord.id）：落库只存 key，回放时按需取字节
    file_id: str | None = Field(
        default=None, min_length=32, max_length=64, pattern=r"^[0-9a-fA-F-]{32,64}$"
    )
    media_type: str | None = None
    alt: str | None = None

    @model_validator(mode="after")
    def _needs_payload(self) -> Self:
        if not (self.url or self.data or self.file_id):
            raise ValueError("image item needs url, data or file_id")
        return self


class VideoItem(BaseItem):
    type: Literal[ItemType.VIDEO] = ItemType.VIDEO
    role: Literal["user", "assistant"] = "user"
    url: str | None = None
    data: str | None = None
    file_id: str | None = Field(
        default=None, min_length=32, max_length=64, pattern=r"^[0-9a-fA-F-]{32,64}$"
    )
    media_type: str | None = None
    alt: str | None = None

    @model_validator(mode="after")
    def _needs_payload(self) -> Self:
        if not (self.url or self.data or self.file_id):
            raise ValueError("video item needs url, data or file_id")
        return self


class FileItem(BaseItem):
    type: Literal[ItemType.FILE] = ItemType.FILE
    role: Literal["user", "assistant"] = "user"
    name: str
    media_type: str = "application/octet-stream"
    data: str
    size: int = 0


class ResourceItem(BaseItem):
    """指向对象存储里一个文件的引用，本体不进消息：模型按 storage_key 取用。

    - storage_key 就是 FileRecord 的 id（透明字符串，模型不解释）。
    - 全面替代 FileItem 的角色：附件和产物都用它，前端渲染成可下载的 chip。
    """

    type: Literal[ItemType.RESOURCE] = ItemType.RESOURCE
    role: Literal["user", "assistant"] = "user"
    storage_key: str = Field(min_length=1, max_length=64)
    name: str
    media_type: str = "application/octet-stream"
    size: int = 0


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
    | FileItem
    | ResourceItem
    | ThinkingItem
    | ToolCallItem
    | ToolResultItem
    | ErrorItem
    | ApprovalRequestItem
    | CallRequestItem
    | CustomItem,
    Field(discriminator="type"),
]

PendingInterrupts = list[PendingInterrupt]


def resource_tag(storage_key: str, name: str, media_type: str) -> str:
    """resource 在上下文里的文本形状；模型照此理解，前端照此打码。"""
    return (
        f'<resource storage_key="{storage_key}" '
        f'original_name="{name}" mime_type="{media_type}"/>'
    )


def resource_items(
    records: Sequence[tuple[Any, str | None]],
    *,
    role: Literal["user", "assistant"] = "user",
) -> list[ResourceItem]:
    """(FileRecord, 提示名) 记录转 ResourceItem；提示名缺省用记录里的名字。"""
    items: list[ResourceItem] = []
    for record, hint in records:
        name = (hint or "").strip() or record.name
        items.append(
            ResourceItem(
                role=role,
                storage_key=str(record.id),
                name=name,
                media_type=record.content_type or "application/octet-stream",
            )
        )
    return items


def item_text(item: RunItem) -> str:
    """检索 / 分支预览用文本；图片视频只留占位。"""
    if isinstance(item, TextItem):
        return item.text
    if isinstance(item, (ImageItem, VideoItem)):
        return item.alt or ("[图片]" if isinstance(item, ImageItem) else "[视频]")
    if isinstance(item, FileItem):
        return item.name
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
    return ""
