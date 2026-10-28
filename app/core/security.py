"""密码哈希（bcrypt）+ JWT 签发/校验 + Fernet 对称加密。"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt
import jwt.exceptions
from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import ConfigurationError, UnauthenticatedError

ACCESS = "access"
REFRESH = "refresh"

# bcrypt 只认前 72 字节；长度上限在 schema 侧用 UTF-8 字节数卡住
_PASSWORD_COST = 12


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    return _cipher(secret_key).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, secret_key: str) -> str:
    try:
        return _cipher(secret_key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ConfigurationError("Unable to decrypt API key; check SECRET_KEY") from exc


@lru_cache(maxsize=16)
def _cipher(secret_key: str) -> Fernet:
    try:
        return Fernet(secret_key.encode())
    except ValueError as exc:
        raise ConfigurationError("SECRET_KEY must be a valid Fernet key") from exc


# ---------------------------------------------------------------- 密码

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_PASSWORD_COST)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    """哈希为空也不许抛异常，一律当密码不匹配。"""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# ---------------------------------------------------------------- JWT

def issue_token(
    user_id: str, token_type: str, *, secret_key: str, expires_in: timedelta
) -> str:
    if not secret_key:
        raise ConfigurationError("SECRET_KEY must be configured")
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + expires_in,
        # 秒级时间戳 + 相同 sub 会签出完全一样的串；jti 保证每次签发唯一
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret_key, algorithm="HS256")


def decode_token(token: str, expected_type: str, *, secret_key: str | None) -> str:
    """校验通过时返回 sub（用户 id）。"""
    if not secret_key:
        raise ConfigurationError("SECRET_KEY must be configured")
    try:
        claims = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise UnauthenticatedError("登录状态无效或已过期") from error
    if claims.get("type") != expected_type:
        raise UnauthenticatedError("令牌类型不匹配")
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise UnauthenticatedError("登录状态无效或已过期")
    return user_id


# ---------------------------------------------------------------- 验证码指针

def code_digest(code: str, secret_key: str) -> str:
    """验证码掺密钥后再入库：库里看到的是摘要，泄露不出可复用的码。"""
    return hmac.new(secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()
