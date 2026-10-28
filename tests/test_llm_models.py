from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import LlmProvider
from app.models.llm_model import LlmModel
from tests.conftest import TEST_USER_ID

BASE_PAYLOAD: dict[str, Any] = {
    "name": "gpt-4.1",
    "provider": "openai",
    "model_name": "gpt-4.1",
    "api_key": "sk-test-secret",
    "context_window": 128000,
    "max_output_tokens": 4096,
    "supports_tools": True,
}


async def create_model(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/models", json={**BASE_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_model_encrypts_and_hides_api_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await create_model(client)

    assert body["name"] == "gpt-4.1"
    assert body["provider"] == "openai"
    assert "api_key" not in body
    assert "api_key_encrypted" not in body

    stored = await db_session.get(LlmModel, int(body["id"]))
    assert stored is not None
    assert stored.api_key_encrypted is not None
    assert stored.api_key_encrypted != "sk-test-secret"


async def test_list_update_and_delete_model(client: AsyncClient, db_session: AsyncSession) -> None:
    first = await create_model(client)
    second = await create_model(client, name="second")
    third = await create_model(client, name="third")

    response = await client.get("/api/v1/models", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert [item["id"] for item in page["items"]] == [second["id"], third["id"]]

    response = await client.patch(
        f"/api/v1/models/{first['id']}",
        json={"max_output_tokens": 2048, "api_key": None},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["max_output_tokens"] == 2048
    assert "api_key" not in updated

    stored = await db_session.get(LlmModel, int(first["id"]))
    assert stored is not None
    assert stored.api_key_encrypted is None

    response = await client.delete(f"/api/v1/models/{first['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/v1/models/{first['id']}")
    assert response.status_code == 404


async def test_duplicate_name_returns_conflict(client: AsyncClient) -> None:
    await create_model(client)
    second = await create_model(client, name="second")

    response = await client.post("/api/v1/models", json={**BASE_PAYLOAD, "name": "second"})
    assert response.status_code == 409

    response = await client.patch(f"/api/v1/models/{second['id']}", json={"name": "gpt-4.1"})
    assert response.status_code == 409


async def test_only_one_default_model(client: AsyncClient) -> None:
    first = await create_model(client, name="first", is_default=True)
    second = await create_model(client, name="second", is_default=True)

    response = await client.get(f"/api/v1/models/{first['id']}")
    assert response.json()["is_default"] is False

    response = await client.get(f"/api/v1/models/{second['id']}")
    assert response.json()["is_default"] is True


async def test_invalid_payload_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/models", json={**BASE_PAYLOAD, "context_window": 0})
    assert response.status_code == 422

    response = await client.post(
        "/api/v1/models", json={**BASE_PAYLOAD, "name": "unknown", "provider": "not-a-provider"}
    )
    assert response.status_code == 422

    response = await client.patch("/api/v1/models/1", json={"name": None})
    assert response.status_code == 422


async def test_storing_api_key_requires_secret_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # 上面有同名 query 时不该把 key 加密写库；HTTP 层此场景被鉴权挡住，直接在服务层验证
    from app.core.exceptions import ConfigurationError
    from app.schemas.llm_model import LlmModelCreate
    from app.services import llm_model as model_service

    with pytest.raises(ConfigurationError, match="SECRET_KEY is required"):
        await model_service.create_model(
            db_session,
            LlmModelCreate(**BASE_PAYLOAD),
            owner_id=TEST_USER_ID,
            secret_key=None,
        )


async def test_every_provider_can_be_created(client: AsyncClient) -> None:
    for provider in LlmProvider:
        response = await client.post(
            "/api/v1/models",
            json={
                **BASE_PAYLOAD,
                "name": provider.value,
                "provider": provider.value,
                "api_key": None,
            },
        )
        assert response.status_code == 201, f"{provider.value}: {response.text}"
        assert response.json()["provider"] == provider.value
