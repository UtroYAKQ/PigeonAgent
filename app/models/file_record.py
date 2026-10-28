"""用户视角的逻辑文件；多行可指向同一个 blob。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class FileRecord(TimestampMixin, Base):
    __tablename__ = "files"
    __table_args__ = (Index("ix_files_owner_id_deleted_at", "owner_id", "deleted_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 上传者；下载时按它校验归属。null 表示匿名上传（Token 尚未接入的调用方）
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    # 原始文件名；下载时经 Content-Disposition 贴回
    name: Mapped[str] = mapped_column(String(255))
    # 指向物理块的 hash；同一内容的多行互不干扰。故意不建外键：
    # blob 被 GC 后，软删的历史行还要保留
    blob_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str | None] = mapped_column(String(128))
    # 软删时间；引用从此消失，物理块等 GC
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    def __repr__(self) -> str:
        return f"FileRecord(id={self.id!r}, owner_id={self.owner_id!r}, name={self.name!r})"
