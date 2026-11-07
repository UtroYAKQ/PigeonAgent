"""指向 FileRecord 的引用类型。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# uuid hex 允许带连字符，所以是 32~64 位；附件、资源、图片/视频 item 共用这一处校验。
FileIdRef = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-fA-F-]{32,64}$", min_length=32, max_length=64)
]

# 工具结果 metadata 里携带 FileRef 的键；落库后转成 ToolResultItem.media
TOOL_MEDIA_METADATA_KEY = "media"


class FileRef(BaseModel):
    """一个文件引用的唯一形状：file_id 是 FileRecord 主键，其余是展示/校验信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # 唯一字段名；写出和读入都只认 file_id。
    file_id: FileIdRef
    name: str = "file"
    media_type: str = "application/octet-stream"
    size: int = 0
