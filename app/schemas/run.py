import json
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.enums import RunKind, RunStatus
from app.schemas.run_item import PendingInterrupt, RunItem, TokenUsage

MAX_TOOL_SCHEMA_CHARS = 4000


class FrontendTool(BaseModel):
    """浏览器声明的工具：模型可以调，结果由前端回填。

    每轮都随请求带上来，所以 run 不存定义——重新生成时模型看到的工具集和上一轮一致。
    """

    model_config = ConfigDict(extra="forbid")

    # OpenAI 兼容接口只接受 ^[a-zA-Z0-9_-]+$ 的工具名，点分会被上游拒成 400，
    # 所以命名空间用下划线分隔，且必须至少有一个。
    name: str = Field(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
    description: str = Field(min_length=1, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def _parameters_are_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            return {"type": "object", "properties": {}}
        if value.get("type") != "object" or not isinstance(value.get("properties"), dict):
            raise ValueError("parameters must be a JSON object schema with properties")
        if len(json.dumps(value, ensure_ascii=False)) > MAX_TOOL_SCHEMA_CHARS:
            raise ValueError("parameters schema is too large")
        return value


class Attachment(BaseModel):
    """一轮用户输入附带的图片/视频：先 POST /files 上传，这里只带记录 id。

    文档走 ResourceRef（模型按 storage_key 取用）——图片视频要以二进制直接进上下文，
    才需要 file_id。kind/name/media_type 由服务端按入库记录归一化。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["image", "video"]
    name: str = Field(min_length=1, max_length=200)
    media_type: str = Field(default="application/octet-stream", min_length=1, max_length=120)
    file_id: str = Field(min_length=32, max_length=64, pattern=r"^[0-9a-fA-F-]{32,64}$")


class ResourceRef(BaseModel):
    """指向已上传文件（POST /files 的产物）的引用；storage_key 就是文件的 id。"""

    model_config = ConfigDict(extra="forbid")

    storage_key: str = Field(min_length=32, max_length=64, pattern=r"^[0-9a-fA-F-]{32,64}$")
    # 可选的展示名；缺了用入库时的名字
    name: str | None = Field(default=None, min_length=1, max_length=200)


class RunCreate(BaseModel):
    """开一轮 run。

    - `input`：新的用户消息，默认接在当前叶子后面。
    - `attachments`：随消息发的图片/视频（只带 file_id）；可以只有附件没有文本。
    - `resources`：已上传文件的引用；文档类附件走这里，提示词里渲染成 `<resource/>` 标签。
    - `input + parent_run_id=null`（显式给 null）：在根处开新分支，用于改第一条提问。
    - `input + parent_run_id=...`：从该 run 处开分支，用于改提问重发。
    - `retry_run_id`：复制这条 run 的用户输入，并从它的父节点另起一条回答（重新生成）。
    """

    model_config = ConfigDict(extra="forbid")

    input: str | None = Field(default=None, min_length=1)
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)
    # 走 /files 上传后的文件引用；提示词里渲染成 <resource/> 标签
    resources: list[ResourceRef] = Field(default_factory=list, max_length=10)
    tools: list[FrontendTool] = Field(default_factory=list, max_length=10)
    parent_run_id: UUID | None = None
    retry_run_id: UUID | None = None
    model_id: int | None = None

    @model_validator(mode="after")
    def _needs_something_to_run(self) -> Self:
        if self.retry_run_id is not None:
            if (
                self.input is not None
                or self.attachments
                or self.resources
                or "parent_run_id" in self.model_fields_set
            ):
                raise ValueError(
                    "retry_run_id cannot be combined with input, attachments or parent_run_id"
                )
            return self
        if self.input is None and not self.attachments and not self.resources:
            raise ValueError("input or attachments is required")
        return self

    @property
    def parent_was_given(self) -> bool:
        return "parent_run_id" in self.model_fields_set


class RunResume(BaseModel):
    """恢复某个中断批次；审批只有 yes/no，外部调用直接给结果值。"""

    model_config = ConfigDict(extra="forbid")

    interrupt_id: UUID
    approvals: dict[str, bool] = Field(default_factory=dict)
    calls: dict[str, Any] = Field(default_factory=dict)
    tools: list[FrontendTool] = Field(default_factory=list, max_length=10)
    model_id: int | None = None


class RunRead(BaseModel):
    run_id: str


class BranchNav(BaseModel):
    """同一父节点下的 turn 版本；leaves 是切分支时要落到的分支末端。"""

    position: int
    total: int
    leaves: list[UUID]


class SessionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    parent_run_id: UUID | None = None
    seq: int
    status: RunStatus
    kind: RunKind = RunKind.TURN
    content: list[RunItem]
    preview: str = ""
    usage: TokenUsage = Field(default_factory=TokenUsage)
    branch: BranchNav | None = None
    created_at: datetime
    updated_at: datetime


class SessionRunList(BaseModel):
    items: list[SessionRunRead]
    has_more: bool | None = None


class PendingBatchRead(BaseModel):
    """一条 run 里声明的、还没有工具结果的未决中断批次。"""

    run_id: UUID
    run_seq: int
    interrupt_id: UUID
    interrupts: list[PendingInterrupt]


class SessionContext(BaseModel):
    runs: list[SessionRunRead]
    messages: list[dict[str, Any]]
