from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Blob(TimestampMixin, Base):
    """物理块：一模一样的内容在桶里只有一份。

    这里不掺任何业务字段；updated_at 被 file_service 触碰后顺带充当
    GC 的宽限锚点（刚有新引用挂上来就绝不会进删除候选）。
    """

    __tablename__ = "blobs"

    # SHA-256 hex，内容即身份
    hash_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    # 桶里的对象 key：uuid 化，不可枚举；一个 blob 永远只对应一个对象
    storage_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    def __repr__(self) -> str:
        return f"Blob(hash_id={self.hash_id!r}, size={self.size!r})"
