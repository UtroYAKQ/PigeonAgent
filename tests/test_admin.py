"""平台管理：统计、用户、会话和操作日志。"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.helpers import make_session


async def test_admin_users_list_reports_fractional_balance(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """余额按 token 线性折算，本来就是小数（49.99…）；列表不能因为它把自己 500 掉。"""
    member, _ = await _register_member(client)
    user = await db_session.get(User, uuid.UUID(member["id"]))
    assert user is not None
    user.credits_balance = 49.993952
    await db_session.commit()

    users = await client.get("/api/v1/admin/users", params={"q": "member-admin"})
    assert users.status_code == 200, users.text
    assert users.json()["items"][0]["credits_balance"] == 49.993952


async def test_admin_users_list_exposes_email_verification(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """未验证和停用是两件事：列表要能分别看到。"""
    member, _ = await _register_member(client)
    user = await db_session.get(User, uuid.UUID(member["id"]))
    assert user is not None
    user.email_verified = False
    user.is_active = False
    await db_session.commit()

    users = await client.get("/api/v1/admin/users", params={"q": "member-admin"})
    assert users.status_code == 200, users.text
    item = users.json()["items"][0]
    assert item["email_verified"] is False
    assert item["is_active"] is False


async def _register_member(client: AsyncClient) -> tuple[dict[str, Any], dict[str, str]]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "member-admin@example.com", "password": "member-password"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    headers = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
    return body["user"], headers


async def test_admin_stats_users_sessions_and_logs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    member, member_headers = await _register_member(client)
    member_id = uuid.UUID(member["id"])
    await make_session(db_session, title="成员会话", owner_id=member_id)

    stats = await client.get("/api/v1/admin/stats")
    assert stats.status_code == 200, stats.text
    data = stats.json()
    assert data["users_total"] >= 2
    assert data["users_admin"] >= 1
    assert data["sessions_total"] >= 1

    users = await client.get("/api/v1/admin/users", params={"q": "member-admin"})
    assert users.status_code == 200
    assert users.json()["total"] == 1
    listed = users.json()["items"][0]
    assert listed["email"] == "member-admin@example.com"
    assert listed["session_count"] == 1

    member_listing = await client.get("/api/v1/admin/users", headers=member_headers)
    assert member_listing.status_code == 403

    disabled = await client.patch(f"/api/v1/admin/users/{member_id}", json={"is_active": False})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_active"] is False

    sessions = await client.get("/api/v1/admin/sessions", params={"q": "成员会话"})
    assert sessions.status_code == 200
    session_items = sessions.json()["items"]
    assert len(session_items) == 1
    session = session_items[0]
    assert session["owner_email"] == "member-admin@example.com"
    assert session["run_count"] == 0

    archived = await client.patch(
        f"/api/v1/admin/sessions/{session['id']}", json={"status": "archived"}
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    logs = await client.get("/api/v1/admin/logs")
    assert logs.status_code == 200
    actions = [item["action"] for item in logs.json()["items"]]
    assert "user.update" in actions
    assert "session.update" in actions

    filtered = await client.get("/api/v1/admin/logs", params={"action": "session.update"})
    assert filtered.status_code == 200
    assert all(item["action"] == "session.update" for item in filtered.json()["items"])


async def test_admin_password_reset_revokes_old_tokens(client: AsyncClient) -> None:
    member, member_headers = await _register_member(client)
    member_id = uuid.UUID(member["id"])

    reset = await client.post(
        f"/api/v1/admin/users/{member_id}/password",
        json={"new_password": "reset-password"},
    )
    assert reset.status_code == 204, reset.text
    assert (await client.get("/api/v1/auth/me", headers=member_headers)).status_code == 401

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": member["email"], "password": "member-password"},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": member["email"], "password": "reset-password"},
    )
    assert new_login.status_code == 200

    me = (await client.get("/api/v1/auth/me")).json()
    self_reset = await client.post(
        f"/api/v1/admin/users/{me['id']}/password",
        json={"new_password": "another-password"},
    )
    assert self_reset.status_code == 422

    logs = await client.get("/api/v1/admin/logs", params={"action": "user.password_reset"})
    assert any(item["target_id"] == str(member_id) for item in logs.json()["items"])


async def test_admin_cannot_lock_themselves_out(client: AsyncClient) -> None:
    me = await client.get("/api/v1/auth/me")
    my_id = me.json()["id"]

    demote = await client.patch(f"/api/v1/admin/users/{my_id}", json={"is_admin": False})
    assert demote.status_code == 422

    disable = await client.patch(f"/api/v1/admin/users/{my_id}", json={"is_active": False})
    assert disable.status_code == 422
