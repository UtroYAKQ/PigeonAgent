"""注册 / 邮箱验证 / 登录 / 刷新 / me / 默认管理员。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import Settings, get_settings
from app.models.user import User
from tests.conftest import TEST_SECRET_KEY

REG = {"email": "user@example.com", "password": "hunter2secret"}
ADMIN = {"email": "admin@pigeon.local", "password": "admin123456"}


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

    async def fake_send_mail(settings: Any, to_email: str, subject: str, body: str) -> None:
        sent.append((to_email, body))

    monkeypatch.setattr("app.services.user.mailer.send_mail", fake_send_mail)
    return sent


def _force_verification(client: Any) -> None:
    """client fixture 覆盖的是全局依赖，这里要走 FastAPI 的 override 字典。"""
    from app.main import app

    app.dependency_overrides[get_settings] = _verification_settings


def _code_of(payloads: list[tuple[str, str]]) -> str:
    candidates: list[str] = re.findall(r"\b\d{6}\b", payloads[-1][1])
    assert candidates
    return candidates[0]


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

async def test_email_verification_flow(client: Any, monkeypatch: Any) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)

    register = await client.post("/api/v1/auth/register", json=REG)
    assert register.status_code == 201
    body = register.json()
    assert body["verification_required"] is True
    assert body["tokens"] is None
    assert len(sent) == 1

    # 未验证时登录 → 409 并自动补发
    blocked = await client.post("/api/v1/auth/login", json=REG)
    assert blocked.status_code == 409
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


async def test_resend_delivers_for_unverified_user(client: Any, monkeypatch: Any) -> None:
    sent = _capture_mail(monkeypatch)
    _force_verification(client)
    await client.post("/api/v1/auth/register", json=REG)
    count = len(sent)
    response = await client.post("/api/v1/auth/resend", json={"email": REG["email"].upper()})
    assert response.status_code == 202
    assert len(sent) == count + 1


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
