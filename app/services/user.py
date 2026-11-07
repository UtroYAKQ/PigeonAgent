"""用户注册 / 邮箱验证 / 登录 / 刷新，以及首启动默认管理员。"""

from __future__ import annotations

import asyncio
import hmac
import logging
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import security
from app.core.config import WEAK_ADMIN_PASSWORDS, Settings
from app.core.exceptions import (
    ConfigurationError,
    ConflictError,
    ForbiddenError,
    MailDeliveryError,
    NotFoundError,
    TooManyRequestsError,
    UnauthenticatedError,
    UnprocessableError,
)
from app.core.ids import parse_uuid
from app.domain.media_type import effective_media_type
from app.domain.time import ensure_utc
from app.infra import mailer
from app.models.file_record import FileRecord
from app.models.user import User
from app.models.user_email_code import REGISTER, EmailCode
from app.schemas.user import (
    LoginIn,
    RegisterIn,
    TokenPairOut,
    UserPreferencesUpdate,
)

logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 15
CODE_MAX_ATTEMPTS = 5
# 同一邮箱两封验证码邮件之间的最小间隔；前一条码 15 分钟内一直有效，不需要更早再发
CODE_SEND_COOLDOWN_SECONDS = 60

# 登录撞上不存在的用户时也烧一遍 bcrypt，抹平响应时序差异
_DUMMY_HASH = security.hash_password("timing-equalizer")


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def _find_user(db: AsyncSession, email: str) -> User | None:
    return (await db.scalars(select(User).where(User.email == email))).first()


def _pair_for(user: User, settings: Settings) -> TokenPairOut:
    secret = settings.secret_key
    if not secret:
        raise ConfigurationError("SECRET_KEY 未配置")
    access = timedelta(minutes=settings.access_token_ttl_minutes)
    return TokenPairOut(
        access_token=security.issue_token(
            str(user.id),
            security.ACCESS,
            secret_key=secret,
            expires_in=access,
            token_version=user.token_version,
        ),
        refresh_token=security.issue_token(
            str(user.id),
            security.REFRESH,
            secret_key=secret,
            expires_in=timedelta(days=settings.refresh_token_ttl_days),
            token_version=user.token_version,
        ),
        expires_in=int(access.total_seconds()),
    )


# ---------------------------------------------------------------- 验证码


async def _issue_code(db: AsyncSession, settings: Settings, email: str, purpose: str) -> bool:
    """生成 6 位码：库里只存 HMAC 摘要；返回验证码邮件是否真的发出去了。"""
    if not settings.smtp_host:
        # 走到这里说明验证已开启（开关本身要求 SMTP），却没配 host：
        # 这封信永远发不出去，必须当场报错，不能假装已送达
        raise ConfigurationError("邮箱验证已开启，但未配置 SMTP_HOST")
    if not settings.secret_key:
        raise ConfigurationError("SECRET_KEY 未配置")
    code = f"{secrets.randbelow(10**6):06d}"
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
    return await mailer.send_mail(
        settings, email, mailer.CODE_SUBJECT, mailer.code_body(code, CODE_TTL_MINUTES)
    )


_MAIL_FAILED_DETAIL = "验证码邮件发送失败，请检查 SMTP 配置后重试"


async def _seconds_since_last_code(db: AsyncSession, email: str, purpose: str) -> float | None:
    """距上一次发码过了多少秒；从没发过返回 None。

    只看时间，不管那条码是否已被消费：冷却要挡的是"同一邮箱几秒内收到第二封"。
    """
    created_at = (
        await db.scalars(
            select(EmailCode.created_at)
            .where(EmailCode.email == email, EmailCode.purpose == purpose)
            .order_by(EmailCode.created_at.desc())
            .limit(1)
        )
    ).first()
    if created_at is None:
        return None
    return (datetime.now(UTC) - ensure_utc(created_at)).total_seconds()


async def _send_code(db: AsyncSession, settings: Settings, email: str, purpose: str) -> None:
    """发码、落库；信没出去就抛错，别让用户对着收不到的验证码干等。

    冷却内不重发：注册/登录顺路发码的那几条路径上，上一条验证码仍在有效期，
    重发只会让攻击者拿一个邮箱烧光 SMTP 配额。
    """
    elapsed = await _seconds_since_last_code(db, email, purpose)
    if elapsed is not None and elapsed < CODE_SEND_COOLDOWN_SECONDS:
        logger.info(
            "Skipped verification email for %s: %ds since the last send (cooldown %ds)",
            email,
            int(elapsed),
            CODE_SEND_COOLDOWN_SECONDS,
        )
        return
    delivered = await _issue_code(db, settings, email, purpose)
    await db.commit()
    if not delivered:
        raise MailDeliveryError(_MAIL_FAILED_DETAIL)


# ---------------------------------------------------------------- 注册 / 验证


async def register(
    db: AsyncSession, settings: Settings, payload: RegisterIn
) -> tuple[User, TokenPairOut | None]:
    """新建用户并发验证码；开了邮箱验证时 tokens 为 None（等 verify 换登录态）。"""
    email = normalize_email(payload.email)
    user = await _find_user(db, email)

    if user is None:
        password_hash = await asyncio.to_thread(security.hash_password, payload.password)
        verified = not settings.is_email_verification_enabled
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=payload.display_name,
            is_active=verified,
            email_verified=verified,
        )
        db.add(user)
        await db.commit()
    elif not user.is_active:
        if not user.email_verified:
            if settings.is_email_verification_enabled:
                # 重新提交未验证账号 = 重新发一封验证码，不重复建行
                await _send_code(db, settings, email, REGISTER)
                return user, None
            # 关掉邮箱验证后不能仅凭“知道邮箱”激活别人的未验证账号
            matched = await asyncio.to_thread(
                security.verify_password, payload.password, user.password_hash
            )
            if not matched:
                raise UnauthenticatedError("邮箱或密码不正确")
            user.email_verified = True
            user.is_active = True
            await db.commit()
            return user, _pair_for(user, settings)
        # 已验证但被管理员停用：注册流程不允许自行恢复
        raise ForbiddenError("账号已停用，请联系管理员")
    else:
        raise ConflictError("该邮箱已注册")

    if settings.is_email_verification_enabled:
        # 用户和验证码都已入库，但信没出去时必须让前端知道
        await _send_code(db, settings, email, REGISTER)
        return user, None
    return user, _pair_for(user, settings)


async def verify_email(db: AsyncSession, settings: Settings, email: str, code: str) -> TokenPairOut:
    email = normalize_email(email)
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
    expires_at = ensure_utc(row.expires_at)
    if expires_at < datetime.now(UTC):
        row.consumed_at = datetime.now(UTC)
        await db.commit()
        raise UnprocessableError("验证码已失效，请重新发送")
    if not settings.secret_key:
        raise ConfigurationError("SECRET_KEY 未配置")
    if not hmac.compare_digest(row.digest, security.code_digest(code, settings.secret_key)):
        row.attempts += 1
        await db.commit()
        raise UnprocessableError("验证码错误")

    user = await _find_user(db, email)
    if user is None:
        raise UnprocessableError("账号不存在，请重新注册")
    row.consumed_at = datetime.now(UTC)
    user.is_active = True
    user.email_verified = True
    await db.commit()
    return _pair_for(user, settings)


async def resend_code(db: AsyncSession, settings: Settings, email: str) -> None:
    email = normalize_email(email)
    user = await _find_user(db, email)
    # 不存在的邮箱保持沉默：别把哪个邮箱注册过与否告诉调用方
    if user is None or user.is_active or user.email_verified:
        return
    if not settings.is_email_verification_enabled:
        # 验证没开就没有"重发"一说，登录时会直接放行；同样保持沉默
        return
    elapsed = await _seconds_since_last_code(db, email, REGISTER)
    if elapsed is not None and elapsed < CODE_SEND_COOLDOWN_SECONDS:
        # 用户主动点"重新发送"，所以要给准信，不能像顺路发码那样静默跳过
        wait = max(1, math.ceil(CODE_SEND_COOLDOWN_SECONDS - elapsed))
        raise TooManyRequestsError(f"验证码刚刚已发送，请 {wait} 秒后再试", retry_after=wait)
    await _send_code(db, settings, email, REGISTER)


# ---------------------------------------------------------------- 登录 / 刷新


async def login(db: AsyncSession, settings: Settings, payload: LoginIn) -> TokenPairOut:
    email = normalize_email(payload.email)
    user = await _find_user(db, email)
    hashed = user.password_hash if user is not None else None
    matched = await asyncio.to_thread(
        security.verify_password, payload.password, hashed or _DUMMY_HASH
    )
    if user is None or not matched:
        raise UnauthenticatedError("邮箱或密码不正确")

    if not user.is_active:
        if not user.email_verified:
            if settings.is_email_verification_enabled:
                # 冷却内 _send_code 不会真发第二封，所以文案只说"信在路上"，不承诺刚发过
                await _send_code(db, settings, email, REGISTER)
                raise ConflictError("邮箱未验证，验证码已发到你的邮箱，请查收")
            user.email_verified = True
            user.is_active = True
            await db.commit()
        else:
            raise ForbiddenError("账号已停用，请联系管理员")

    return _pair_for(user, settings)


async def refresh_tokens(db: AsyncSession, settings: Settings, refresh_token: str) -> TokenPairOut:
    user_id, token_version = security.decode_token(
        refresh_token, security.REFRESH, secret_key=settings.secret_key
    )
    parsed_id = parse_uuid(user_id)
    if parsed_id is None:
        raise UnauthenticatedError("登录状态无效或已过期")
    user = await db.get(User, parsed_id)
    if user is None or not user.is_active or user.token_version != token_version:
        raise UnauthenticatedError("登录状态无效或已过期")
    return _pair_for(user, settings)


# ---------------------------------------------------------------- 个人账号


async def update_profile(db: AsyncSession, user: User, data: dict[str, Any]) -> User:
    if "display_name" in data:
        value = data["display_name"]
        user.display_name = value.strip() if isinstance(value, str) and value.strip() else None
    if "avatar_file_id" in data:
        avatar_id = data["avatar_file_id"]
        if avatar_id is None:
            user.avatar_file_id = None
        else:
            record = await db.get(FileRecord, avatar_id)
            if record is None or record.deleted_at is not None or record.owner_id != user.id:
                raise UnprocessableError("头像文件不存在或不属于当前用户")
            if not effective_media_type(record.name, record.content_type).startswith("image/"):
                raise UnprocessableError("头像必须是图片文件")
            user.avatar_file_id = record.id
    await db.commit()
    await db.refresh(user)
    return user


async def update_preferences(db: AsyncSession, user: User, payload: UserPreferencesUpdate) -> User:
    patch = payload.model_dump(exclude_unset=True, exclude_none=True)
    if patch:
        # 只并入这次真正提交的键：整份写回会把服务端默认值伪装成用户的选择，
        # 下次登录就盖掉了这台设备本地的主题
        user.preferences = {**(user.preferences or {}), **patch}
        await db.commit()
    return user


async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    *,
    settings: Settings,
) -> TokenPairOut:
    matched = await asyncio.to_thread(
        security.verify_password, current_password, user.password_hash
    )
    if not matched:
        raise UnprocessableError("当前密码不正确")
    user.password_hash = await asyncio.to_thread(security.hash_password, new_password)
    # 改密后旧 access/refresh 立即失效，当前设备换发一对新令牌
    user.token_version += 1
    await db.commit()
    return _pair_for(user, settings)


async def reset_password(
    db: AsyncSession, user_id: uuid.UUID, *, actor_id: uuid.UUID, new_password: str
) -> None:
    """管理员重置：不校验旧密码，同时作废该用户所有已签发令牌。"""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    if user.id == actor_id:
        raise UnprocessableError("请在账号设置中修改自己的密码")
    user.password_hash = await asyncio.to_thread(security.hash_password, new_password)
    user.token_version += 1
    await db.commit()


async def logout_all_devices(db: AsyncSession, user: User) -> None:
    """登出所有设备：递增令牌版本，让已签发的 access/refresh 一律验不过。

    这是"发现口令可能泄露"时的应急闸门——本机退出只清本地令牌，撤不掉别人手里的
    refresh（它默认 7 天有效），只有这里能让所有会话立刻失效。
    """
    user.token_version += 1
    await db.commit()


# ---------------------------------------------------------------- 默认管理员


async def ensure_admin(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    """确保配置的管理员账号存在；邮箱被改过时不能在旧账号存在后就跳过。"""
    email = normalize_email(settings.admin_email)
    async with factory() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            return
        if settings.admin_password in WEAK_ADMIN_PASSWORDS:
            logger.error(
                "Refusing to seed admin %s with the default ADMIN_PASSWORD; "
                "set a strong value in .env and restart",
                email,
            )
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
                email_verified=True,
            )
        )
        await session.commit()
        logger.info("Seeded admin: %s（请尽快修改密码）", email)
