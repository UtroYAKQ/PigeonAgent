from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.run_items import TokenUsage
from app.enums import SessionStatus
from app.schemas.user import Password


class AdminStatsRead(BaseModel):
    users_total: int
    users_active: int
    users_admin: int
    sessions_total: int
    sessions_active: int
    sessions_archived: int
    runs_total: int
    runs_failed: int


class AdminUserRead(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    is_admin: bool
    is_active: bool
    # 注册后邮箱是否完成验证；和「停用」是两件事
    email_verified: bool = True
    created_at: datetime
    session_count: int
    last_active_at: datetime | None
    credits_balance: float = 0


class AdminUserList(BaseModel):
    items: list[AdminUserRead]
    total: int


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=64)
    is_admin: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field_name in {"is_admin", "is_active"} & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class AdminPasswordResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: Password


class AdminSessionRead(BaseModel):
    id: UUID
    title: str | None
    owner_id: UUID | None
    owner_email: str | None
    owner_display_name: str | None
    status: SessionStatus
    model_id: int | None
    has_unread: bool
    active_run_id: str | None
    usage: TokenUsage
    run_count: int
    last_run_at: datetime
    created_at: datetime


class AdminSessionList(BaseModel):
    items: list[AdminSessionRead]
    total: int


class AdminSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SessionStatus


class AdminOperationLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str | None = None
    kind: str
    actor_email: str | None = None
    method: str | None = None
    path: str | None = None
    route: str | None = None
    query: Any = None
    request_body: Any = None
    status_code: int | None = None
    response_body: Any = None
    duration_ms: int | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    request_truncated: bool = False
    response_truncated: bool = False
    client_ip: str | None = None
    user_agent: str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime


class AdminOperationLogList(BaseModel):
    items: list[AdminOperationLogRead]
    total: int


class AdminCreditAdjustIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 正数充值、负数扣减；0 没有意义。支持小数：按 token 折算的积分不到 1
    delta: float
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_nonzero(self) -> Self:
        if self.delta == 0:
            raise ValueError("delta cannot be 0")
        return self


class AdminCreditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    user_email: str | None = None
    user_display_name: str | None = None
    delta: float
    balance_after: float
    reason: str
    run_id: UUID | None = None
    model_kind: str | None = None
    model_id: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    created_at: datetime


class AdminCreditLogList(BaseModel):
    items: list[AdminCreditLogRead]
    total: int


class AdminChatLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    user_email: str | None = None
    user_display_name: str | None = None
    session_id: UUID | None = None
    run_id: UUID | None = None
    kind: str
    status: str
    model_name: str | None = None
    usage: TokenUsage
    credits_charged: float
    images_generated: int
    error: str | None = None
    duration_ms: int | None = None
    created_at: datetime
    finished_at: datetime | None = None


class AdminChatLogList(BaseModel):
    items: list[AdminChatLogRead]
    total: int
