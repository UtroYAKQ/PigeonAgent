from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai.image import ImageModel


async def test_capabilities_expose_only_public_image_model_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            ImageModel(
                name="Seedream",
                provider="ark",
                model_name="doubao-seedream-4-0",
                sizes=["1024x1024", "1536x1024"],
                default_size="1536x1024",
                max_images=2,
                is_default=True,
            ),
            ImageModel(
                name="Retired",
                provider="openai",
                model_name="gpt-image-1",
                is_active=False,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/v1/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["image_generation"] is True
    assert body["default_image_model_id"] is not None
    assert [item["name"] for item in body["image_models"]] == ["Seedream"]
    option = body["image_models"][0]
    assert option["default_size"] == "1536x1024"
    assert option["sizes"] == ["1024x1024", "1536x1024"]
    assert option["max_images"] == 2
    assert option["is_default"] is True
    # 管理字段不下发给普通用户
    assert "base_url" not in option
    assert "api_key_encrypted" not in option
    assert "model_name" not in option


async def test_capabilities_hide_image_generation_without_active_models(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        ImageModel(
            name="Retired",
            provider="openai",
            model_name="gpt-image-1",
            is_active=False,
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/capabilities")).json()
    assert body["image_generation"] is False
    assert body["image_models"] == []
    assert body["default_image_model_id"] is None
