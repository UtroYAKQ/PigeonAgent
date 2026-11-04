"""同源媒体直链的签名。

浏览器原生 <img> 带不了 Bearer，所以给媒体一条短时效签名 URL。过期戳取「窗口末尾」，
同一窗口里签出的 exp 与 sig 都相同，URL 稳定，浏览器缓存才真正命中；服务端不存状态，
只用 HMAC 重算。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from uuid import UUID


def _signing_key(secret: str) -> bytes:
    # 不直接拿 Fernet 的密钥材料当 HMAC key，派生一份专用子密钥
    return hmac.new(secret.encode(), b"pigeon-file-link", hashlib.sha256).digest()


def window_expiry(now: float, ttl_seconds: int) -> int:
    """下一个窗口的末尾：链接至少还能用 ttl 秒，最多 2*ttl 秒。"""
    return (int(now // ttl_seconds) + 2) * ttl_seconds


def signature(secret: str, file_id: UUID, expires_at: int) -> str:
    message = f"{file_id}:{expires_at}".encode()
    return hmac.new(_signing_key(secret), message, hashlib.sha256).hexdigest()


def issue(
    secret: str, file_id: UUID, ttl_seconds: int, *, now: float | None = None
) -> tuple[int, str]:
    moment = time.time() if now is None else now
    expires_at = window_expiry(moment, ttl_seconds)
    return expires_at, signature(secret, file_id, expires_at)


def verify(
    secret: str,
    file_id: UUID,
    expires_at: int,
    token: str,
    *,
    now: float | None = None,
) -> bool:
    moment = time.time() if now is None else now
    if expires_at < moment:
        return False
    return hmac.compare_digest(signature(secret, file_id, expires_at), token)
