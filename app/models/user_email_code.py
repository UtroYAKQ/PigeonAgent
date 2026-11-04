import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin

# Purpose 常量；后续重置密码等场景在这里加
REGISTER = "register"


class EmailCode(TimestampMixin, Base):
    """一次性邮箱验证码；最大的业务字段就是 purpose。"""

    __tablename__ = "email_codes"
    __table_args__ = (Index("ix_email_codes_email_purpose", "email", "purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), index=True)
    # HMAC-SHA256(code, SECRET_KEY) hex；库里看不到可用明文
    digest: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(16), default=REGISTER)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
