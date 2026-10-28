"""会话分组：组 CRUD、会话归属与删组回落未分组。"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def create_group(client: AsyncClient, name: str = "项目") -> dict[str, Any]:
    response = await client.post("/api/v1/groups", json={"name": name})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def create_session(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/sessions", json={"title": "会话", **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_group_crud_and_count(client: AsyncClient) -> None:
    group = await create_group(client, "日常")
    assert group["name"] == "日常"
    assert group["session_count"] == 0

    await create_session(client, group_id=group["id"])
    listed = (await client.get("/api/v1/groups")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["session_count"] == 1

    renamed = await client.patch(f"/api/v1/groups/{group['id']}", json={"name": "私人"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "私人"
    assert renamed.json()["session_count"] == 1


async def test_groups_sort_by_creation_order(client: AsyncClient) -> None:
    first = await create_group(client, "a")
    second = await create_group(client, "b")
    items = (await client.get("/api/v1/groups")).json()["items"]
    assert [item["id"] for item in items] == [first["id"], second["id"]]
    assert items[0]["sort_order"] < items[1]["sort_order"]


async def test_session_can_live_without_a_group(client: AsyncClient) -> None:
    created = await create_session(client)
    assert created["group_id"] is None


async def test_move_session_between_groups_and_clear(client: AsyncClient) -> None:
    work = await create_group(client, "工作")
    side = await create_group(client, "副业")
    session = await create_session(client, group_id=work["id"])
    assert session["group_id"] == work["id"]

    moved = await client.patch(f"/api/v1/sessions/{session['id']}", json={"group_id": side["id"]})
    assert moved.json()["group_id"] == side["id"]

    cleared = await client.patch(f"/api/v1/sessions/{session['id']}", json={"group_id": None})
    assert cleared.json()["group_id"] is None

    # 不带 group_id 的更新不该动分组
    titled = await client.patch(f"/api/v1/sessions/{session['id']}", json={"title": "改名"})
    assert titled.json()["group_id"] is None
    assert titled.json()["title"] == "改名"


async def test_delete_group_keeps_sessions_ungrouped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    group = await create_group(client, "临时")
    session = await create_session(client, group_id=group["id"])

    assert (await client.delete(f"/api/v1/groups/{group['id']}")).status_code == 204

    after = await client.get(f"/api/v1/sessions/{session['id']}")
    assert after.json()["group_id"] is None


async def test_unknown_group_is_rejected(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/sessions", json={"title": "x", "group_id": 999})
    ).status_code == 404
    session = await create_session(client)
    patch = await client.patch(f"/api/v1/sessions/{session['id']}", json={"group_id": 999})
    assert patch.status_code == 404
    assert (await client.patch("/api/v1/groups/999", json={"name": "x"})).status_code == 404
    assert (await client.delete("/api/v1/groups/999")).status_code == 404


async def test_blank_and_overlong_names_are_rejected(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/groups", json={"name": "   "})).status_code == 422
    assert (await client.post("/api/v1/groups", json={"name": "名" * 61})).status_code == 422
    assert (await client.post("/api/v1/groups", json={})).status_code == 422


async def test_group_names_may_repeat(client: AsyncClient) -> None:
    first = await create_group(client, "同名")
    second = await create_group(client, "同名")
    assert first["id"] != second["id"]
    assert (await client.get("/api/v1/groups")).json()["total"] == 2
