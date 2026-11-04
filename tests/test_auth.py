"""注册 / 邮箱验证 / 登录 / 刷新 / me / 默认管理员。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import LOGIN_LIMIT, REGISTER_LIMIT
from app.core import security
from app.core.config import Settings, get_settings
from app.models.file_record import FileRecord
from app.models.user import User
from app.models.user_email_code import EmailCode
from tests.conftest import TEST_SECRET_KEY

REG = {"email": "user@example.com", "password": "hunter2secret"}
ADMIN = {"email": "admin@pigeon.local", "password": "test-admin-password"}


def _bearer(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _verification_settings() -> Settings:
    return Settings(
        secret_key=TEST_SECRET_KEY,
        smtp_host="stub",
        smtp_port=2525,
        smtp_tls="none",
        email_verification_required=True,
        email_from="Pigeon <no-reply@example.com>",
    )


def _capture_mail(monkeypatch: Any) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    async def fake_send_mail(settings: Any, to_email: str, subject: str, body: str) -> bool:
        sent.append((to_email, body))
        return True

    monkeypatch.setattr("app.services.user.mailer.send_mail", fake_send_mail)
    return sent


def _break_mail(monkeypatch: Any) -> None:
    async def fake_send_mail(settings: Any, to_email: str, subject: str, body: str) -> bool:
        return False

    monkeypatch.setattr("app.services.user.mailer.send_mail", fake_send_mail)


def _force_verification(client: Any) -> None:
    """client fixture 覆盖的是全局依赖，这里要走 FastAPI 的 override 字典。"""
    from app.main import app

    app.dependency_overrides[get_settings] = _verification_settings


def _code_of(payloads: list[tuple[str, str]]) -> str:
    candidates: list[str] = re.findall(r"\b\d{6}\b", payloads[-1][1])
    assert candidates
    return candidates[0]


async def _age_out_codes(db_session: AsyncSession, minutes: int = 2) -> None:
    """把已发出的验证码推到 60 秒发送冷却之外；冷却本身另有专项用例。"""
    await db_session.execute(
        update(EmailCode).values(created_at=datetime.now(UTC) - timedelta(minutes=minutes))
    )
    await db_session.commit()


# ---------------------------------------------------------------- 无 SMTP 直通


async def test_register_without_smtp_gives_tokens_directly(client: Any) -> None:
    response = await client.post("/api/v1/auth/register", json=REG)
    assert response.status_code == 201
    body = response.json()
    assert body["verification_required"] is False
    assert body["user"]["email"] == "user@example.com"
    assert body["tokens"]["token_type"] == "bearer"

    me = await client.get("/api/v1/auth/me", headers=_bearer(body["tokens"]))
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


async def test_duplicate_register_409(client: Any) -> None:
    assert (await client.post("/api/v1/auth/register", json=REG)).status_code == 201
    conflict = await client.post("/api/v1/auth/register", json=REG)
    assert conflict.status_code == 409
    # 大小写不同也拦住
    assert (
        await client.post("/api/v1/auth/register", json={**REG, "email": REG["email"].upper()})
    ).status_code == 409


async def test_register_rejects_bad_payload(client: Any) -> None:
    for payload in [
        {"email": "nope", "password": "hunter2secret"},
        {"email": "ok@example.com", "password": "short"},
    ]:
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 422


@pytest.mark.parametrize(
    "email",
    [
        "nope",
        "a@b",
        "a@b..com",
        "a@-b.com",
        "a@b-.com",
        "a@b.c",
        "a@b.123",
        "a@b.c0m",
        "a b@example.com",
        "a@b.com,",
        "a..b@example.com",
        ".a@example.com",
        "a.@example.com",
        "a@example.com.",
    ],
)
async def test_invalid_email_is_rejected_before_sending(
    client: Any, monkeypatch: Any, email: str
) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)

    response = await client.post(
        "/api/v1/auth/register",
        json={**REG, "email": email},
    )
    assert response.status_code == 422, response.text
    assert "邮箱" in response.text
    assert sent == [], "格式不合法时不能发出验证码邮件"


async def test_internal_domain_email_still_passes(client: Any, monkeypatch: Any) -> None:
    """默认管理员和自建 SMTP 常用 .local，格式校验不能把它们误伤。"""
    sent = _capture_mail(monkeypatch)
    _force_verification(client)

    response = await client.post(
        "/api/v1/auth/register",
        json={**REG, "email": "local-user@pigeon.local"},
    )
    assert response.status_code == 201, response.text
    assert len(sent) == 1


async def test_login_refresh_and_wrong_password(client: Any) -> None:
    await client.post("/api/v1/auth/register", json=REG)
    wrong = await client.post("/api/v1/auth/login", json=REG | {"password": "wrong password"})
    assert wrong.status_code == 401

    login = await client.post("/api/v1/auth/login", json=REG)
    assert login.status_code == 200
    tokens = login.json()

    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 200
    assert refresh.json()["access_token"] != tokens["access_token"]

    # refresh token 不能当 access token 用
    wrong_type = {"Authorization": f"Bearer {tokens['refresh_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=wrong_type)).status_code == 401


async def test_me_requires_auth(client: Any) -> None:
    anonymous = {"Authorization": ""}
    assert (await client.get("/api/v1/auth/me", headers=anonymous)).status_code == 401
    garbage = {"Authorization": "Bearer garbage"}
    assert (await client.get("/api/v1/auth/me", headers=garbage)).status_code == 401


# ---------------------------------------------------------------- 邮箱验证流程


async def test_email_verification_flow(
    client: Any, monkeypatch: Any, db_session: AsyncSession
) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)

    register = await client.post("/api/v1/auth/register", json=REG)
    assert register.status_code == 201
    body = register.json()
    assert body["verification_required"] is True
    assert body["tokens"] is None
    assert len(sent) == 1

    # 未验证时登录 → 409；60 秒内不补发，前一条码还在有效期，攻击者烧不动 SMTP 配额
    blocked = await client.post("/api/v1/auth/login", json=REG)
    assert blocked.status_code == 409
    assert len(sent) == 1

    # 冷却过了才补发，验证码以最后一封为准
    await _age_out_codes(db_session)
    aged = await client.post("/api/v1/auth/login", json=REG)
    assert aged.status_code == 409
    assert len(sent) == 2

    code = _code_of(sent)
    ok = await client.post("/api/v1/auth/verify", json={"email": REG["email"], "code": code})
    assert ok.status_code == 200
    me = await client.get("/api/v1/auth/me", headers=_bearer(ok.json()))
    assert me.status_code == 200

    # 验证码一次性：同一个码再来一次不行
    again = await client.post("/api/v1/auth/verify", json={"email": REG["email"], "code": code})
    assert again.status_code == 422


async def test_wrong_code_counts_attempts(client: Any, monkeypatch: Any) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)

    await client.post("/api/v1/auth/register", json=REG)
    code = _code_of(sent)
    right = (int(code) + 1) % 1_000_000
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/verify", json={"email": REG["email"], "code": f"{right:06d}"}
        )
        assert response.status_code == 422
    # 超过次数上限后正确码也被判失效
    expired = await client.post("/api/v1/auth/verify", json={"email": REG["email"], "code": code})
    assert expired.status_code == 422


async def test_resend_silent_for_unknown_email(client: Any, monkeypatch: Any) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)
    response = await client.post("/api/v1/auth/resend", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    assert sent == []  # 不存在的邮箱也回 202，不暴露谁注册过


async def test_resend_delivers_for_unverified_user(
    client: Any, monkeypatch: Any, db_session: AsyncSession
) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)
    await client.post("/api/v1/auth/register", json=REG)
    await _age_out_codes(db_session)
    count = len(sent)
    response = await client.post("/api/v1/auth/resend", json={"email": REG["email"].upper()})
    assert response.status_code == 202
    assert len(sent) == count + 1


# ---------------------------------------------------------------- 发信失败必须说出来


async def test_register_reports_mail_failure(client: Any, monkeypatch: Any) -> None:
    """信没发出去就不能回 201 让人干等。"""
    _break_mail(monkeypatch)
    _force_verification(client)

    response = await client.post("/api/v1/auth/register", json=REG)
    assert response.status_code == 502
    assert "发送失败" in response.json()["detail"]


async def test_login_reports_mail_failure(
    client: Any, monkeypatch: Any, db_session: AsyncSession
) -> None:
    _capture_mail(monkeypatch)
    _force_verification(client)
    await client.post("/api/v1/auth/register", json=REG)
    await _age_out_codes(db_session)

    _break_mail(monkeypatch)
    response = await client.post("/api/v1/auth/login", json=REG)
    assert response.status_code == 502
    assert "发送失败" in response.json()["detail"]


async def test_resend_reports_mail_failure(
    client: Any, monkeypatch: Any, db_session: AsyncSession
) -> None:
    _capture_mail(monkeypatch)
    _force_verification(client)
    await client.post("/api/v1/auth/register", json=REG)
    await _age_out_codes(db_session)

    _break_mail(monkeypatch)
    response = await client.post("/api/v1/auth/resend", json={"email": REG["email"]})
    assert response.status_code == 502
    assert "发送失败" in response.json()["detail"]


def test_sender_falls_back_to_smtp_user() -> None:
    """发件人不是登录账号时，服务商直接 501，所以没配就用账号本身。"""
    assert Settings(smtp_user="me@example.com", smtp_host="stub").sender_address == "me@example.com"
    assert (
        Settings(
            smtp_user="me@example.com", email_from="PigeonAgent <no-reply@pigeon.local>"
        ).sender_address
        == "me@example.com"
    )
    # 显式配置过就照用，不覆盖用户意图
    assert (
        Settings(smtp_user="me@example.com", email_from="Pigeon <hi@example.com>").sender_address
        == "Pigeon <hi@example.com>"
    )


# ---------------------------------------------------------------- 默认管理员


async def test_admin_seeded_once(db_session: AsyncSession) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import user as user_service

    settings = Settings(
        secret_key=TEST_SECRET_KEY,
        admin_email=ADMIN["email"],
        admin_password=ADMIN["password"],
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await user_service.ensure_admin(factory, settings)

    admin = (await db_session.scalars(select(User).where(User.email == ADMIN["email"]))).first()
    assert admin is not None and admin.is_admin and admin.is_active
    assert security.verify_password(ADMIN["password"], admin.password_hash)

    # 幂等：库里已有用户后再次种子不再加行
    await user_service.ensure_admin(factory, settings)
    count = len((await db_session.scalars(select(User))).all())
    assert count == 1


async def test_admin_not_seeded_with_default_password(db_session: AsyncSession) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import user as user_service

    settings = Settings(
        _env_file=None,
        secret_key=TEST_SECRET_KEY,
        admin_email=ADMIN["email"],
        admin_password="change-me",
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await user_service.ensure_admin(factory, settings)

    admin = (await db_session.scalars(select(User).where(User.email == ADMIN["email"]))).first()
    assert admin is None


async def test_admin_created_when_configured_email_changes(db_session: AsyncSession) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services import user as user_service

    old = User(
        email="old-admin@pigeon.local",
        password_hash=security.hash_password("old-password"),
        is_admin=True,
        is_active=True,
    )
    db_session.add(old)
    await db_session.commit()

    settings = Settings(
        _env_file=None,
        secret_key=TEST_SECRET_KEY,
        admin_email="new-admin@pigeon.local",
        admin_password="new-admin-password",
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await user_service.ensure_admin(factory, settings)

    created = (
        await db_session.scalars(select(User).where(User.email == "new-admin@pigeon.local"))
    ).first()
    assert created is not None and created.is_admin and created.is_active
    assert security.verify_password("new-admin-password", created.password_hash)

    await user_service.ensure_admin(factory, settings)
    assert len((await db_session.scalars(select(User))).all()) == 2


# ---------------------------------------------------------------- 个人账号


async def test_user_preferences_stores_only_explicit_choices(client: Any) -> None:
    email = "preferences@example.com"
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "preference-pass"}
    )
    body = registered.json()
    # 没表过态的新账号一个键都不返回，前端才能继续用这台设备本地的主题
    assert body["user"]["preferences"] == {}
    headers = _bearer(body["tokens"])

    updated = await client.patch(
        "/api/v1/auth/me/preferences",
        headers=headers,
        json={"theme": "dark", "auto_expand_thinking": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["preferences"] == {"theme": "dark", "auto_expand_thinking": True}

    # 局部更新只加自己改过的键，不能顺手把服务端默认值写成用户的选择
    second = await client.patch(
        "/api/v1/auth/me/preferences",
        headers=headers,
        json={"send_shortcut": "ctrl-enter", "wrap_code": True},
    )
    assert second.status_code == 200, second.text
    expected = {
        "theme": "dark",
        "auto_expand_thinking": True,
        "send_shortcut": "ctrl-enter",
        "wrap_code": True,
    }
    assert second.json()["preferences"] == expected
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["preferences"] == expected

    invalid = await client.patch(
        "/api/v1/auth/me/preferences", headers=headers, json={"theme": "neon"}
    )
    assert invalid.status_code == 422
    unknown = await client.patch(
        "/api/v1/auth/me/preferences", headers=headers, json={"unknown_key": True}
    )
    assert unknown.status_code == 422
    assert (
        await client.patch(
            "/api/v1/auth/me/preferences", headers={"Authorization": ""}, json={"theme": "dark"}
        )
    ).status_code == 401


async def test_register_cannot_activate_inactive_account_without_password(
    client: Any, db_session: AsyncSession
) -> None:
    user = User(
        email="dormant@example.com",
        password_hash=security.hash_password("correct-password"),
        is_active=False,
        email_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    wrong = await client.post(
        "/api/v1/auth/register",
        json={"email": "dormant@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert not user.is_active

    right = await client.post(
        "/api/v1/auth/register",
        json={"email": "dormant@example.com", "password": "correct-password"},
    )
    assert right.status_code == 201, right.text
    assert right.json()["tokens"]["access_token"]
    assert user.is_active


async def test_disabled_account_cannot_self_reactivate(
    client: Any, db_session: AsyncSession
) -> None:
    user = User(
        email="disabled@example.com",
        password_hash=security.hash_password("correct-password"),
        is_active=False,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "disabled@example.com", "password": "correct-password"},
    )
    assert register.status_code == 403

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@example.com", "password": "correct-password"},
    )
    assert login.status_code == 403
    assert not user.is_active


async def test_profile_avatar_upload_and_clear(
    client: Any, db_session: AsyncSession, test_user_id: Any
) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "avatar@example.com", "password": "hunter2secret"},
    )
    token = registered.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = UUID(registered.json()["user"]["id"])

    avatar = FileRecord(
        owner_id=user_id,
        name="avatar.png",
        blob_hash="a" * 64,
        content_type="image/png",
    )
    text_file = FileRecord(
        owner_id=user_id,
        name="avatar.txt",
        blob_hash="b" * 64,
        content_type="text/plain",
    )
    db_session.add_all([avatar, text_file])
    await db_session.commit()

    updated = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"avatar_file_id": str(avatar.id)}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["avatar_file_id"] == str(avatar.id)
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["avatar_file_id"] == str(
        avatar.id
    )

    # 非图片不能作为头像
    rejected = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"avatar_file_id": str(text_file.id)},
    )
    assert rejected.status_code == 422
    assert "头像必须是图片" in rejected.json()["detail"]

    # 别人的文件不能拿来当头像（默认测试用户是管理员）
    stranger = FileRecord(
        owner_id=test_user_id,
        name="stranger.png",
        blob_hash="c" * 64,
        content_type="image/png",
    )
    db_session.add(stranger)
    await db_session.commit()
    denied = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"avatar_file_id": str(stranger.id)},
    )
    assert denied.status_code == 422

    cleared = await client.patch("/api/v1/auth/me", headers=headers, json={"avatar_file_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["avatar_file_id"] is None


async def test_profile_and_password_updates(client: Any) -> None:
    email = "profile@example.com"
    old_password = "old-password"
    new_password = "new-password"

    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": old_password}
    )
    token = registered.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    updated = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"display_name": "  新名字  "}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "新名字"
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()["display_name"] == "新名字"

    wrong = await client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"current_password": "wrong-password", "new_password": new_password},
    )
    assert wrong.status_code == 422

    too_short = await client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"current_password": old_password, "new_password": "short"},
    )
    assert too_short.status_code == 422

    changed = await client.post(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"current_password": old_password, "new_password": new_password},
    )
    assert changed.status_code == 200
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}

    # 改密后旧 access token 立即失效，新令牌可用
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=new_headers)).status_code == 200

    stale = await client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert stale.status_code == 401
    fresh = await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert fresh.status_code == 200


# ---------------------------------------------------------------- 认证限流


async def test_login_throttled_per_email(client: Any) -> None:
    """同一个邮箱的尝试数有窗口上限；键是账号，所以换邮箱不受影响。"""
    wrong = {"email": REG["email"], "password": "wrong-password"}
    for _ in range(LOGIN_LIMIT):
        assert (await client.post("/api/v1/auth/login", json=wrong)).status_code == 401

    blocked = await client.post("/api/v1/auth/login", json=REG)
    assert blocked.status_code == 429
    assert blocked.json()["retry_after"] > 0

    other = {"email": "someone-else@example.com", "password": "another-secret-pass"}
    assert (await client.post("/api/v1/auth/login", json=other)).status_code == 401


async def test_register_throttled_per_email(client: Any) -> None:
    """注册可以换着邮箱刷，但同一个邮箱在短时间内只能试这么多次。"""
    for _ in range(REGISTER_LIMIT):
        await client.post("/api/v1/auth/register", json=REG)
    blocked = await client.post("/api/v1/auth/register", json=REG)
    assert blocked.status_code == 429


async def test_resend_blocked_within_cooldown(client: Any, monkeypatch: Any) -> None:
    """60 秒内点"重新发送"要给出准信，而不是静默多发一封。"""
    sent = _capture_mail(monkeypatch)
    _force_verification(client)
    await client.post("/api/v1/auth/register", json=REG)

    response = await client.post("/api/v1/auth/resend", json={"email": REG["email"]})
    assert response.status_code == 429
    assert "刚刚已发送" in response.json()["detail"]
    assert response.json()["retry_after"] > 0
    assert len(sent) == 1


# ---------------------------------------------------------------- 会话撤销


async def test_logout_all_invalidates_issued_tokens(client: Any) -> None:
    """本机退出只清本地令牌；登出所有设备才作废已签发的 access 与 refresh。"""
    email = "logout-all@example.com"
    password = "logout-all-secret"
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    tokens = registered.json()["tokens"]
    headers = _bearer(tokens)
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    assert (await client.post("/api/v1/auth/logout-all", headers=headers)).status_code == 200

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    renewed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert renewed.status_code == 401

    # 重新登录拿到的新令牌照常可用：撤的是旧版本，不是这个账号
    again = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert again.status_code == 200
    fresh = _bearer(again.json())
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 200
