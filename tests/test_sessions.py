from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session_run import SessionRun
from tests.helpers import append_user_run


async def create_session(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/sessions", json={"title": "会话", **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_and_get_session(client: AsyncClient) -> None:
    created = await create_session(client)

    assert created["status"] == "active"
    assert created["run_seq"] == 0
    assert created["format_version"] == 5
    assert created["active_run_id"] is None
    assert created["active_leaf_run_id"] is None
    assert "pending_interrupts" not in created

    response = await client.get(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_list_sessions_paginates_and_filters(client: AsyncClient) -> None:
    for index in range(3):
        await create_session(client, title=f"s{index}")

    response = await client.get("/api/v1/sessions", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    await client.patch(f"/api/v1/sessions/{page['items'][0]['id']}", json={"status": "archived"})
    response = await client.get("/api/v1/sessions", params={"status": "archived"})
    assert response.json()["total"] == 1


async def test_update_session(client: AsyncClient) -> None:
    created = await create_session(client)

    response = await client.patch(
        f"/api/v1/sessions/{created['id']}", json={"title": "新标题", "status": "archived"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "新标题"
    assert response.json()["status"] == "archived"

    response = await client.patch(f"/api/v1/sessions/{created['id']}", json={"status": None})
    assert response.status_code == 422


async def test_create_session_rejects_unknown_model(client: AsyncClient) -> None:
    response = await client.post("/api/v1/sessions", json={"model_id": 999})
    assert response.status_code == 422
    assert response.json() == {"detail": "Model 999 not found"}


async def test_get_missing_session_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_delete_session_cascades_runs(client: AsyncClient, db_session: AsyncSession) -> None:
    created = await create_session(client)
    from uuid import UUID

    session_id = UUID(created["id"])
    run = await append_user_run(db_session, session_id, "会被级联删除")

    response = await client.delete(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/v1/sessions/{created['id']}")
    assert response.status_code == 404

    remaining = await db_session.scalars(select(SessionRun).where(SessionRun.id == run.id))
    assert list(remaining) == []
