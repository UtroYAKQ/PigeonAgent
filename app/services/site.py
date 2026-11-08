"""站点品牌资源：Logo 存在对象存储的固定 key，配置表只记公开地址。"""

from __future__ import annotations

import hashlib

from app.core.config import Settings

MAX_LOGO_BYTES = 2 * 1024 * 1024
ALLOWED_LOGO_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


def logo_key(settings: Settings) -> str:
    prefix = settings.s3_prefix.strip("/")
    return f"{prefix}/site/logo" if prefix else "site/logo"


def logo_url(settings: Settings, body: bytes) -> str:
    """内容 hash 做版本号：换 Logo 后 URL 变，浏览器缓存自然失效。"""
    version = hashlib.sha256(body).hexdigest()[:12]
    prefix = settings.api_v1_prefix.rstrip("/")
    return f"{prefix}/configs/public/logo?v={version}"
