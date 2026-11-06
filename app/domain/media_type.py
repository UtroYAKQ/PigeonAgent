"""媒体类型判定：扩展名优先，魔数兜底。

同一份文件在发布、读取、上传链路必须得到同一个 mime，禁止各工具各自猜。
"""

from __future__ import annotations

import mimetypes

_MAGIC_TYPES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)


def detect_media_type(name: str | None, data: bytes | None = None) -> str:
    if name:
        guessed = mimetypes.guess_type(name)[0]
        if guessed:
            return guessed
    if data:
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        for signature, media_type in _MAGIC_TYPES:
            if data.startswith(signature):
                return media_type
    return "application/octet-stream"
