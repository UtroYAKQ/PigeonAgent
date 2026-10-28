"""用户注册 / 邮箱验证 / 登录 / 刷新，以及首启动默认管理员。"""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    ConflictError,
    UnauthenticatedError,
    UnprocessableError,
)
from app.models.user import User
from app.models.user_email_code import REGISTER, EmailCode
from app.schemas.user import LoginIn, RegisterIn, TokenPairOut
from app.services import mailer

logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 15
CODE_MAX_ATTEMPTS = 5

# 登录撞上不存在的用户时也烧一遍 bcrypt，抹平响应时序差异
_DUMMY_HASH = security.hash_password("timing-equalizer")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _pair_for(user: User, settings: Settings) -> TokenPairOut:
    secret = settings.secret_key
    if not secret:
        raise ConfigurationError("SECRET_KEY must be configured")
    access = timedelta(minutes=settings.access_token_ttl_minutes)
    return TokenPairOut(
        access_token=security.issue_token(
            str(user.id), security.ACCESS, secret_key=secret, expires_in=access
        ),
        refresh_token=security.issue_token(
            str(user.id),
            security.REFRESH,
            secret_key=secret,
            expires_in=timedelta(days=settings.refresh_token_ttl_days),
        ),
        expires_in=int(access.total_seconds()),
    )


# ---------------------------------------------------------------- 验证码

async def _issue_code(
    db: AsyncSession, settings: Settings, email: str, purpose: str
) -> None:
    """生成 6 位码：库里只存 HMAC 摘要，发信失败留日志但不回滚入库。"""
    if not settings.smtp_host:
        return
    if not settings.secret_key:
        raise ConfigurationError("SECRET_KEY must be configured")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    now = datetime.now(UTC)
    await db.execute(
        update(EmailCode)
        .where(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    db.add(
        EmailCode(
            email=email,
            digest=security.code_digest(code, settings.secret_key),
            purpose=purpose,
            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    await mailer.send_mail(
        settings, email, mailer.CODE_SUBJECT, mailer.code_body(code, CODE_TTL_MINUTES)
    )


# ---------------------------------------------------------------- 注册 / 验证

async def register(
    db: AsyncSession, settings: Settings, payload: RegisterIn
) -> tuple[User, TokenPairOut | None]:
    """新建用户并发验证码；开了邮箱验证时 tokens 为 None（等 verify 换登录态）。"""
    email = _normalize_email(payload.email)
    user = (await db.scalars(select(User).where(User.email == email))).first()

    if user is None:
        password_hash = await asyncio.to_thread(security.hash_password, payload.password)
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=payload.display_name,
            is_active=not settings.email_verification_enabled,
        )
        db.add(user)
        await db.commit()
    elif not user.is_active:
        if settings.email_verification_enabled:
            # 重新提交未验证账号 = 重新发一封验证码，不重复建行
            await _issue_code(db, settings, email, REGISTER)
            await db.commit()
            return user, None
        user.is_active = True
        await db.commit()
        return user, _pair_for(user, settings)
    else:
        raise ConflictError("该邮箱已注册")

    if settings.email_verification_enabled:
        await _issue_code(db, settings, email, REGISTER)
        await db.commit()
        return user, None
    return user, _pair_for(user, settings)


async def verify_email(
    db: AsyncSession, settings: Settings, email: str, code: str
) -> TokenPairOut:
    email = _normalize_email(email)
    row = (
        await db.scalars(
            select(EmailCode)
            .where(
                EmailCode.email == email,
                EmailCode.purpose == REGISTER,
                EmailCode.consumed_at.is_(None),
            )
            .order_by(EmailCode.created_at.desc())
        )
    ).first()
    if row is None or row.attempts >= CODE_MAX_ATTEMPTS:
        raise UnprocessableError("验证码已失效，请重新发送")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        # SQLite 的 DateTime(timezone=True) 读回来不带 tz
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        row.consumed_at = datetime.now(UTC)
        await db.commit()
        raise UnprocessableError("验证码已失效，请重新发送")
    if not settings.secret_key:
        raise ConfigurationError("SECRET_KEY must be configured")
    if not hmac.compare_digest(row.digest, security.code_digest(code, settings.secret_key)):
        row.attempts += 1
        await db.commit()
        raise UnprocessableError("验证码错误")

    user = (await db.scalars(select(User).where(User.email == email))).first()
    if user is None:
        raise UnprocessableError("账号不存在，请重新注册")
    row.consumed_at = datetime.now(UTC)
    user.is_active = True
    await db.commit()
    return _pair_for(user, settings)


async def resend_code(db: AsyncSession, settings: Settings, email: str) -> None:
    email = _normalize_email(email)
    user = (await db.scalars(select(User).where(User.email == email))).first()
    # 不存在的邮箱保持沉默：别把哪个邮箱注册过与否告诉调用方
    if user is not None and not user.is_active:
        await _issue_code(db, settings, email, REGISTER)
        await db.commit()


# ---------------------------------------------------------------- 登录 / 刷新

async def login(db: AsyncSession, settings: Settings, payload: LoginIn) -> TokenPairOut:
    email = _normalize_email(payload.email)
    user = (await db.scalars(select(User).where(User.email == email))).first()
    hashed = user.password_hash if user is not None else None
    matched = await asyncio.to_thread(
        security.verify_password, payload.password, hashed or _DUMMY_HASH
    )
    if user is None or not matched:
        raise UnauthenticatedError("邮箱或密码不正确")

    if not user.is_active:
        if settings.email_verification_enabled:
            await _issue_code(db, settings, email, REGISTER)
            await db.commit()
            raise ConflictError("邮箱未验证，验证码已重新发送")
        user.is_active = True
        await db.commit()

    return _pair_for(user, settings)


async def refresh_tokens(
    db: AsyncSession, settings: Settings, refresh_token: str
) -> TokenPairOut:
    user_id = security.decode_token(refresh_token, security.REFRESH, secret_key=settings.secret_key)
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise UnauthenticatedError("登录状态无效或已过期")
    return _pair_for(user, settings)


# ---------------------------------------------------------------- 默认管理员

async def ensure_admin(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    """库为空时种下默认管理员；之后启动每次都直接跳过。"""
    async with factory() as session:
        if (await session.scalars(select(User.id).limit(1))).first() is not None:
            return
        email = _normalize_email(settings.admin_email)
        clash = (await session.scalars(select(User.id).where(User.email == email))).first()
        if clash is not None:
            logger.warning("Admin email %s already taken; default admin skipped", email)
            return
        session.add(
            User(
                email=email,
                password_hash=await asyncio.to_thread(
                    security.hash_password, settings.admin_password
                ),
                display_name="管理员",
                is_admin=True,
                is_active=True,
            )
        )
        await session.commit()
        logger.info("Seeded default admin: %s（请尽快修改 ADMIN_PASSWORD）", email)
