"""指向 FileRecord 主键的引用类型。"""

from typing import Annotated

from pydantic import StringConstraints

# uuid hex 允许带连字符，所以是 32~64 位；附件、资源、图片/视频 item 共用这一处校验。
FileIdRef = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-fA-F-]{32,64}$", min_length=32, max_length=64)
]
