import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, Uuid, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 登录标识；大小写视为同一个邮箱
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # bcrypt 哈希，60 字符
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(64))
    # 头像文件（files.id）；展示时走带鉴权的文件接口
    avatar_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # 未通过邮箱验证的注册都停在这里
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # 邮箱是否已验证；与 is_active 分开，管理员停用后不能靠重新注册/登录自我激活
    email_verified: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # 改密或管理员重置后递增，旧 JWT 随之失效
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # 积分余额；只是 credit_ledgers 的冗余投影，对账以流水为准。
    # 小数：按 token 线性折算可能远小于 1，取整会把小用量放大几百倍
    credits_balance: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    # 个人 UI 偏好；只存用户显式改过的键，缺键表示这个账号在该项上没表过态。
    # 不参与权限判断
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB(), "postgresql"),
        default=dict,
        server_default=text("'{}'"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!r}, email={self.email!r}, "
            f"is_admin={self.is_admin!r}, is_active={self.is_active!r})"
        )
