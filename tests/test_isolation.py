"""数据隔离：新用户看不到既有用户的会话、分组与模型。"""

from __future__ import annotations

from httpx import AsyncClient


async def _new_user(client: AsyncClient, token_email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register", json={"email": token_email, "password": "long-enough"}
    )
    assert response.status_code == 201, response.text
    tokens = response.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {tokens}"}


def _no_auth() -> dict[str, str]:
    return {"Authorization": ""}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    for method, path in [
        ("GET", "/api/v1/sessions"),
        ("POST", "/api/v1/sessions"),
        ("GET", "/api/v1/groups"),
        ("GET", "/api/v1/models"),
        ("POST", "/api/v1/sessions/00000000-0000-0000-0000-000000000001/runs/resume"),
    ]:
        if method == "POST":
            response = await client.post(path, json={}, headers=_no_auth())
        else:
            response = await client.get(path, headers=_no_auth())
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


async def test_sessions_are_invisible_to_other_users(client: AsyncClient) -> None:
    mine = await client.post("/api/v1/sessions", json={"title": "我的会话"})
    assert mine.status_code == 201, mine.text
    session_id = mine.json()["id"]

    stranger = await _new_user(client, "stranger1@example.com")
    response = await client.get(f"/api/v1/sessions/{session_id}", headers=stranger)
    assert response.status_code == 404
    listing = await client.get("/api/v1/sessions", headers=stranger)
    assert listing.status_code == 200 and listing.json()["items"] == []

    stranger_delete = await client.delete(f"/api/v1/sessions/{session_id}", headers=stranger)
    assert stranger_delete.status_code == 404

    update = await client.patch(
        f"/api/v1/sessions/{session_id}", headers=stranger, json={"title": "改"}
    )
    assert update.status_code == 404


async def test_groups_and_models_are_owned(client: AsyncClient) -> None:
    group = await client.post("/api/v1/groups", json={"name": "私有组"})
    assert group.status_code == 201
    model = await client.post(
        "/api/v1/models",
        json={
            "name": "私有模型",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        },
    )
    assert model.status_code == 201

    stranger = await _new_user(client, "stranger2@example.com")
    groups = (await client.get("/api/v1/groups", headers=stranger)).json()
    assert groups["items"] == []
    models = (await client.get("/api/v1/models", headers=stranger)).json()
    assert models["items"] == []

    # 别人的分组/模型一律 404，不能改名也不能删
    assert (
        await client.patch(
            f"/api/v1/groups/{group.json()['id']}", headers=stranger, json={"name": "改"}
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/models/{model.json()['id']}", headers=stranger)
    ).status_code == 404


async def test_sessions_cannot_reference_foreign_resources(client: AsyncClient) -> None:
    model = (
        await client.post(
            "/api/v1/models",
            json={"name": "私有模型2", "provider": "openai", "model_name": "gpt-4o-mini"},
        )
    ).json()
    stranger = await _new_user(client, "stranger3@example.com")

    response = await client.post(
        "/api/v1/sessions", headers=stranger, json={"title": "偷模型", "model_id": model["id"]}
    )
    assert response.status_code == 422

    # run / 事件流也进不来
    mine = (await client.post("/api/v1/sessions", json={"title": "我的会话"})).json()
    assert (
        await client.get(
            f"/api/v1/sessions/{mine['id']}/runs/00000000-0000-0000-0000-000000000002/events",
            headers=stranger,
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/sessions/{mine['id']}/runs/00000000-0000-0000-0000-000000000002/cancel",
            headers=stranger,
        )
    ).status_code == 404


async def test_anonymous_files_stay_public(client: AsyncClient) -> None:
    from tests.test_files import FakeStorage, storage_override

    # 匿名上传的文件走 OptionalUserDep 语义：所有人可见（既有约定）
    fake = FakeStorage()
    storage_override(fake)
    anonymous = await client.post(
        "/api/v1/files", headers=_no_auth(), files={"file": ("open.txt", b"hi", None)}
    )
    assert anonymous.status_code == 201, anonymous.text
    stranger = await _new_user(client, "stranger4@example.com")
    visible = await client.get(
        f"/api/v1/files/{anonymous.json()['id']}", headers=stranger, follow_redirects=False
    )
    assert visible.status_code == 307
