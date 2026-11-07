from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class AppConfig(TimestampMixin, Base):
    """应用配置项：数据库值覆盖环境变量，value 为空表示沿用环境变量。"""

    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 配置键，同时对应 Settings 的字段名
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 分组，前端按它折叠展示
    category: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512))
    # ConfigValueType 的字符串值
    value_type: Mapped[str] = mapped_column(String(16))
    # 密钥类配置：入库前用 SECRET_KEY 加密，接口永远不回显明文
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    value: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"AppConfig(id={self.id!r}, key={self.key!r})"
