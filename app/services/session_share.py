"""会话只读分享：口令签发、校验、列表与撤销。

口令本身不落库：库里是 sha256 哈希（公开读取按它精确匹配）与 Fernet 密文
（只为了让主人能在「我的分享」里再次把链接复制出来）。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, GoneError, NotFoundError
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.time import ensure_utc
from app.models.session import ChatSession
from app.models.session_share import SessionShare
from app.schemas.session_share import ShareRead

# 32 字节 ≈ 43 个 base64url 字符：链接是不可猜测的能力凭证
TOKEN_BYTES = 32
# 过期与撤销/不存在回同一句话，不让探测者从状态码文案区分出这条链接曾经有效
SHARE_GONE_DETAIL = "分享链接已失效"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_key(settings: Settings) -> str:
    if not settings.secret_key:
        raise ConfigurationError("SECRET_KEY 未配置")
    return settings.secret_key


async def create_share(
    db: AsyncSession, settings: Settings, *, session: ChatSession, expires_in_days: int
) -> ShareRead:
    """签发一条链接；明文口令只在这一次随返回值出去，库里只留哈希与密文。"""
    secret_key = _require_key(settings)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    share = SessionShare(
        session_id=session.id,
        token_hash=_token_hash(token),
        token_encrypted=encrypt_secret(token, secret_key),
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)
    return ShareRead(
        id=share.id,
        session_id=session.id,
        session_title=session.title,
        token=token,
        expires_at=share.expires_at,
        visit_count=share.visit_count,
        last_visited_at=None,
        created_at=share.created_at,
    )


async def list_shares(
    db: AsyncSession, settings: Settings, *, owner_id: uuid.UUID
) -> list[ShareRead]:
    """这个账号所有还有效的链接，新的在前；已过期的不占位。"""
    secret_key = _require_key(settings)
    rows = (
        await db.execute(
            select(SessionShare, ChatSession.title)
            .join(ChatSession, ChatSession.id == SessionShare.session_id)
            .where(ChatSession.owner_id == owner_id)
            .order_by(SessionShare.created_at.desc(), SessionShare.id)
        )
    ).all()
    now = datetime.now(UTC)
    shares: list[ShareRead] = []
    for share, title in rows:
        if ensure_utc(share.expires_at) <= now:
            continue
        shares.append(
            ShareRead(
                id=share.id,
                session_id=share.session_id,
                session_title=title,
                token=decrypt_secret(share.token_encrypted, secret_key),
                expires_at=share.expires_at,
                visit_count=share.visit_count,
                last_visited_at=share.last_visited_at,
                created_at=share.created_at,
            )
        )
    return shares


async def revoke_share(db: AsyncSession, *, share_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """撤销即删除：链接本就有到期日，留一条已撤销的行没有意义，操作日志里另有痕迹。"""
    share = (
        await db.scalars(
            select(SessionShare)
            .join(ChatSession, ChatSession.id == SessionShare.session_id)
            .where(SessionShare.id == share_id, ChatSession.owner_id == owner_id)
        )
    ).first()
    if share is None:
        raise NotFoundError(f"Share {share_id} not found")
    await db.delete(share)
    await db.commit()


async def resolve_share(db: AsyncSession, token: str) -> tuple[SessionShare, ChatSession]:
    """公开读取的入口：口令换回 (链接行, 会话)。"""
    share = (
        await db.scalars(select(SessionShare).where(SessionShare.token_hash == _token_hash(token)))
    ).first()
    if share is None:
        raise GoneError(SHARE_GONE_DETAIL)
    session = await db.get(ChatSession, share.session_id)
    if session is None or ensure_utc(share.expires_at) <= datetime.now(UTC):
        raise GoneError(SHARE_GONE_DETAIL)
    # 读一次就记一次：分享页是只读的，这唯一一次写就是"有人看过"的全部信息
    share.visit_count += 1
    share.last_visited_at = datetime.now(UTC)
    await db.commit()
    return share, session
