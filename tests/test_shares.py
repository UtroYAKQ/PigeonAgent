"""会话只读分享：签发、匿名读取、到期与撤销，以及跨账号隔离。"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session_share import SessionShare


async def _session_id(client: AsyncClient, title: str = "分享用会话") -> str:
    response = await client.post("/api/v1/sessions", json={"title": title})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _share(client: AsyncClient, session_id: str, days: int = 7) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/shares", json={"session_id": session_id, "expires_in_days": days}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _anonymous() -> dict[str, str]:
    """分享页访客没有登录态：显式清空 client 夹具的默认令牌。"""
    return {"Authorization": ""}


async def _stranger(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "stranger-pass"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


async def test_share_read_is_anonymous_and_trimmed(client: AsyncClient) -> None:
    link = await _share(client, await _session_id(client, title="公开的会话"))
    assert len(link["token"]) >= 32

    view = await client.get(f"/api/v1/public/shares/{link['token']}", headers=_anonymous())
    assert view.status_code == 200, view.text
    body = view.json()
    # 只给认得出对话的东西：会话 id、模型、用量、未读状态都不下发
    assert body["session"] == {
        "title": "公开的会话",
        "created_at": body["session"]["created_at"],
        "last_run_at": body["session"]["last_run_at"],
    }
    assert set(body) == {"session", "runs", "has_more", "expires_at"}
    assert body["has_more"] is False


async def test_public_read_counts_visits(client: AsyncClient, db_session: AsyncSession) -> None:
    link = await _share(client, await _session_id(client))

    for _ in range(2):
        assert (
            await client.get(f"/api/v1/public/shares/{link['token']}", headers=_anonymous())
        ).status_code == 200

    share = (
        await db_session.execute(select(SessionShare).where(SessionShare.id == UUID(link["id"])))
    ).scalar_one()
    assert share.visit_count == 2
    assert share.last_visited_at is not None


async def test_token_is_never_stored_in_plaintext(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """库被备份或泄露时，拿到的必须不是一串可用链接。"""
    link = await _share(client, await _session_id(client))
    rows = (await db_session.execute(select(SessionShare))).scalars().all()
    stored = f"{[row.token_hash for row in rows]}{[row.token_encrypted for row in rows]}"

    assert link["token"] not in stored


async def test_expired_share_stops_working(client: AsyncClient, db_session: AsyncSession) -> None:
    link = await _share(client, await _session_id(client))
    await db_session.execute(
        update(SessionShare).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()

    assert (
        await client.get(f"/api/v1/public/shares/{link['token']}", headers=_anonymous())
    ).status_code == 410
    # 到期的链接不再占用「我的分享」列表
    assert (await client.get("/api/v1/shares")).json() == []


async def test_revoked_share_stops_working(client: AsyncClient) -> None:
    link = await _share(client, await _session_id(client))
    assert [item["id"] for item in (await client.get("/api/v1/shares")).json()] == [link["id"]]

    assert (await client.delete(f"/api/v1/shares/{link['id']}")).status_code == 204
    assert (
        await client.get(f"/api/v1/public/shares/{link['token']}", headers=_anonymous())
    ).status_code == 410
    assert (await client.get("/api/v1/shares")).json() == []


async def test_unknown_token_looks_exactly_like_a_dead_link(client: AsyncClient) -> None:
    """撤销掉的与从没存在过的，回同样的码和文案，不给探测者任何信号。"""
    link = await _share(client, await _session_id(client))
    await client.delete(f"/api/v1/shares/{link['id']}")

    dead = await client.get(f"/api/v1/public/shares/{link['token']}", headers=_anonymous())
    unknown = await client.get(f"/api/v1/public/shares/{'x' * 43}", headers=_anonymous())
    assert dead.status_code == unknown.status_code == 410
    assert dead.json()["detail"] == unknown.json()["detail"]


async def test_cannot_share_or_revoke_another_users_session(client: AsyncClient) -> None:
    session_id = await _session_id(client)
    stranger = await _stranger(client, "stranger-share@example.com")

    blocked = await client.post(
        "/api/v1/shares",
        json={"session_id": session_id, "expires_in_days": 7},
        headers=stranger,
    )
    assert blocked.status_code == 404

    link = await _share(client, session_id)
    assert (
        await client.delete(f"/api/v1/shares/{link['id']}", headers=stranger)
    ).status_code == 404
    # 陌生人自己的列表里也不该看到它
    assert (await client.get("/api/v1/shares", headers=stranger)).json() == []


async def test_share_expiry_must_be_within_range(client: AsyncClient) -> None:
    session_id = await _session_id(client)
    for days in (0, 366):
        response = await client.post(
            "/api/v1/shares", json={"session_id": session_id, "expires_in_days": days}
        )
        assert response.status_code == 422, f"expires_in_days={days} -> {response.status_code}"
