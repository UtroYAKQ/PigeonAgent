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

_EXTENSIONS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/bmp": "bmp",
}

_UNKNOWN = "application/octet-stream"


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
    return _UNKNOWN


def effective_media_type(
    name: str | None, content_type: str | None, data: bytes | None = None
) -> str:
    """FileRecord 的有效 mime：真实 content_type 优先，缺失/octet 时按扩展名和内容兜底。"""
    value = (content_type or "").strip().lower()
    if value and value != _UNKNOWN:
        return value
    return detect_media_type(name, data)


def extension_for(media_type: str) -> str:
    """媒体类型到文件扩展名；生成图片命名与 mime 口径保持同一张表。"""
    return _EXTENSIONS.get(media_type) or (
        mimetypes.guess_extension(media_type, strict=False) or ".bin"
    ).lstrip(".")
