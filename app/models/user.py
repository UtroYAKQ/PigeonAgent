import uuid

from sqlalchemy import Boolean, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    # 登录标识；大小写视为同一个邮箱
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # bcrypt 哈希，60 字符
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(64))
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # 未通过邮箱验证的注册都停在这里
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!r}, email={self.email!r}, "
            f"is_admin={self.is_admin!r}, is_active={self.is_active!r})"
        )
