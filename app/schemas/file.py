import uuid

from pydantic import BaseModel, Field

_SHA = r"^[0-9a-f]{64}$"


class FileRead(BaseModel):
    """一次登记的结果；url 是短时效签名链接，过期重新拉就行。"""

    id: uuid.UUID
    name: str
    size: int
    content_type: str | None = None
    sha256: str


class FilePrepare(BaseModel):
    """秒传探测入口：先报 name/size/hash，命中就不传字节。"""

    name: str = Field(max_length=255)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=_SHA, min_length=64, max_length=64)
    content_type: str | None = None


class FilePrepareOut(BaseModel):
    deduplicated: bool
    file: FileRead | None = None
    # 没命中时的 presign PUT 上传套餐
    upload_id: uuid.UUID | None = None
    upload_url: str | None = None
    expires_in: int | None = None
