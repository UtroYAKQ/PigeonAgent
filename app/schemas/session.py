from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import SessionStatus
from app.schemas.run_item import TokenUsage


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model_id: int | None = None
    group_id: int | None = None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model_id: int | None = None
    status: SessionStatus | None = None
    # 传 null 表示移出分组；不带这个键表示不动分组
    group_id: int | None = None

    @model_validator(mode="after")
    def reject_null_status(self) -> Self:
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    model_id: int | None
    group_id: int | None = None
    status: SessionStatus
    format_version: int
    run_seq: int
    active_run_id: str | None
    active_run_expires_at: datetime | None = None
    # 当前分支的叶子 run；上下文、分页和重新生成都从它往根走。
    active_leaf_run_id: UUID | None = None
    # 当前分支还有几个没解决的中断批次（列表用一次查询算出来）
    pending_batches: int = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)
    last_run_at: datetime
    created_at: datetime
    updated_at: datetime


class SessionList(BaseModel):
    items: list[SessionRead]
    total: int


class LeafSwitch(BaseModel):
    """切换当前分支；leaf_run_id 为 None 表示回到空会话。"""

    model_config = ConfigDict(extra="forbid")

    leaf_run_id: UUID | None
