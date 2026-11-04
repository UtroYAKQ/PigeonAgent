import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
)

from app.core.email import validated_email

# bcrypt 只处理前 72 字节；按 UTF-8 字节数卡死，避免中文密码被静默截断
PASSWORD_MIN = 8
PASSWORD_MAX_BYTES = 72


def _password_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(f"密码不能超过 {PASSWORD_MAX_BYTES} 个字节（UTF-8）")
    return value


Password = Annotated[str, Field(min_length=PASSWORD_MIN), AfterValidator(_password_bytes)]
# 登录/旧密码不按字节卡上限：历史账号可能超过 72 字节，bcrypt 会按旧行为截断
PasswordInput = Annotated[str, Field(min_length=1, max_length=72)]
Email = Annotated[str, Field(max_length=254), AfterValidator(validated_email)]

ThemePreference = Literal["light", "dark", "system"]
SendShortcut = Literal["enter", "ctrl-enter"]


class RegisterIn(BaseModel):
    email: Email
    password: Password
    display_name: str | None = Field(default=None, max_length=64)


class VerifyIn(BaseModel):
    email: Email
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginIn(BaseModel):
    email: Email
    password: PasswordInput


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


class EmailIn(BaseModel):
    """只要邮箱的入口（重发验证码）。"""

    email: Email


class ProfileUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=64)
    avatar_file_id: uuid.UUID | None = None


class StoredPreferences(BaseModel):
    """账号里显式存过的偏好。没存过的键不出现在响应里，前端才能保留本地缓存的那份。"""

    model_config = ConfigDict(extra="ignore")

    theme: ThemePreference | None = None
    send_shortcut: SendShortcut | None = None
    auto_expand_thinking: bool | None = None
    auto_expand_tool_details: bool | None = None
    wrap_code: bool | None = None

    @model_serializer(mode="wrap")
    def _omit_unset(
        self, handler: "Callable[[StoredPreferences], dict[str, Any]]"
    ) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class UserPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: ThemePreference | None = None
    send_shortcut: SendShortcut | None = None
    auto_expand_thinking: bool | None = None
    auto_expand_tool_details: bool | None = None
    wrap_code: bool | None = None


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: PasswordInput
    new_password: Password


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterOut(BaseModel):
    """没开邮箱验证时一并返回登录态；开了则只告知道验证码已发。"""

    verification_required: bool
    user: "UserRead | None" = None
    tokens: TokenPairOut | None = None


class MessageOut(BaseModel):
    """只回一句话的接口（重发验证码这类不区分结果的响应）。"""

    detail: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_file_id: uuid.UUID | None = None
    is_admin: bool
    is_active: bool
    created_at: datetime
    # 积分余额；随 /auth/me 下发，侧栏和设置页直接展示
    credits_balance: float = 0.0
    preferences: StoredPreferences = Field(default_factory=StoredPreferences)

    @field_validator("preferences", mode="before")
    @classmethod
    def _normalize_preferences(cls, value: object) -> object:
        return value or {}


RegisterOut.model_rebuild()
