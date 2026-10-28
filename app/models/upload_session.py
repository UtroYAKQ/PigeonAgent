"""在途上传会话：presign 上传路径的登记表，超时由 GC 收尾。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class UploadSession(TimestampMixin, Base):
    __tablename__ = "file_upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # null 同 FileRecord.owner_id：匿名上传路径
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # 客户端声明的完整 SHA-256；完成时服务端亲算复核
    declared_sha256: Mapped[str] = mapped_column(String(64))
    declared_size: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(128))
    # 上传目标：临时 key（不可枚举），完成后搬运到 blobs 正式 key
    storage_key: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
