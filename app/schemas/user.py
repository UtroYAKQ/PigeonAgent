import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# bcrypt 只处理前 72 字节，直接在入口处卡死
PASSWORD_MIN = 8
PASSWORD_MAX = 72
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Email = Annotated[str, Field(max_length=254, pattern=_EMAIL_PATTERN)]


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    display_name: str | None = Field(default=None, max_length=64)


class VerifyIn(BaseModel):
    email: Email
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class LoginIn(BaseModel):
    email: Email
    password: str


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


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


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    is_admin: bool
    is_active: bool
    created_at: datetime


RegisterOut.model_rebuild()
