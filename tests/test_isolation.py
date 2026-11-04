"""数据隔离：会话与分组按用户隔离；模型全局共享，只有管理员能配置。"""

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


async def test_groups_are_owned_but_models_are_shared(client: AsyncClient) -> None:
    group = await client.post("/api/v1/groups", json={"name": "私有组"})
    assert group.status_code == 201
    model = await client.post(
        "/api/v1/models",
        json={
            "name": "共享模型",
            "provider": "openai",
            "model_name": "gpt-4o-mini",
        },
    )
    assert model.status_code == 201
    model_id = model.json()["id"]

    stranger = await _new_user(client, "stranger2@example.com")
    groups = (await client.get("/api/v1/groups", headers=stranger)).json()
    assert groups["items"] == []

    # 模型对所有成员可见，单个也能读
    models = (await client.get("/api/v1/models", headers=stranger)).json()
    assert [item["id"] for item in models["items"]] == [model_id]
    assert (await client.get(f"/api/v1/models/{model_id}", headers=stranger)).status_code == 200

    # 分组仍然只属于本人；模型写入只留给管理员
    assert (
        await client.patch(
            f"/api/v1/groups/{group.json()['id']}", headers=stranger, json={"name": "改"}
        )
    ).status_code == 404
    assert (
        await client.patch(f"/api/v1/models/{model_id}", headers=stranger, json={"name": "改"})
    ).status_code == 403
    assert (await client.delete(f"/api/v1/models/{model_id}", headers=stranger)).status_code == 403


async def test_sessions_cannot_reference_other_users_sessions(client: AsyncClient) -> None:
    model = (
        await client.post(
            "/api/v1/models",
            json={"name": "共享模型2", "provider": "openai", "model_name": "gpt-4o-mini"},
        )
    ).json()
    stranger = await _new_user(client, "stranger3@example.com")

    # 模型是共享的，别的成员可以拿它开会话
    response = await client.post(
        "/api/v1/sessions",
        headers=stranger,
        json={"title": "共享模型会话", "model_id": model["id"]},
    )
    assert response.status_code == 201, response.text

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


async def test_files_require_login(client: AsyncClient) -> None:
    from tests.test_files import FakeStorage, storage_override

    storage_override(FakeStorage())
    anonymous = await client.post(
        "/api/v1/files", headers=_no_auth(), files={"file": ("open.txt", b"hi", None)}
    )
    assert anonymous.status_code == 401, "文件接口不再接受匿名上传"
    assert (await client.get("/api/v1/files", headers=_no_auth())).status_code == 401
