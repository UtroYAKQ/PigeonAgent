from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)

# 每个会话最多启用几个 MCP 服务器；能力接口会把这个上限下发给前端
MAX_MCP_SERVERS = 5


def _validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url 必须是带 host 的 http/https 地址")
    if parsed.username or parsed.password:
        raise ValueError("url 不能携带用户名或密码")
    return value


McpServerName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
# 工具名会变成 mcp_<slug>__<tool>，只留小写字母、数字和下划线
McpSlug = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=32, pattern=r"^[a-z0-9_]+$"),
]
McpUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
    AfterValidator(_validate_url),
]


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: McpServerName
    slug: McpSlug
    url: McpUrl
    description: str | None = Field(default=None, max_length=500)
    # 留空表示不需要认证
    auth: SecretStr | None = None
    enabled: bool = True
    requires_approval: bool = True
    defer_loading: bool = True
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: McpServerName | None = None
    slug: McpSlug | None = None
    url: McpUrl | None = None
    description: str | None = Field(default=None, max_length=500)
    # 不传表示保持原 token；传 null 或空串表示清空
    auth: SecretStr | None = None
    enabled: bool | None = None
    requires_approval: bool | None = None
    defer_loading: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=10, le=600)

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_fields(self) -> Self:
        non_nullable = {
            "name",
            "slug",
            "url",
            "enabled",
            "requires_approval",
            "defer_loading",
            "timeout_seconds",
        }
        for field_name in non_nullable & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class McpToolInfo(BaseModel):
    name: str
    description: str | None = None


class McpServerTestResult(BaseModel):
    ok: bool
    tools: list[McpToolInfo] = Field(default_factory=list)
    error: str | None = None


class McpServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    url: str
    description: str | None
    has_auth: bool
    enabled: bool
    requires_approval: bool
    defer_loading: bool
    timeout_seconds: int
    tool_count: int
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class McpServerList(BaseModel):
    items: list[McpServerRead]
    total: int


class McpServerOption(BaseModel):
    """前台只拿选择器需要的信息，不含地址和凭证。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    requires_approval: bool
    defer_loading: bool
    tool_count: int
