from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from app.infra import image_factory
from app.models.image_model import ImageModel


def _record(**overrides: Any) -> ImageModel:
    values: dict[str, Any] = {
        "id": 1,
        "name": "Seedream",
        "provider": "ark",
        "icon": None,
        "model_name": "doubao-seedream-4-0-250828",
        "base_url": None,
        "api_key_encrypted": None,
        "sizes": ["1024x1024"],
        "default_size": "1024x1024",
        "max_images": 4,
        "quality": None,
        "is_active": True,
        "is_default": True,
    }
    values.update(overrides)
    return ImageModel(**values)


def test_cn_provider_uses_its_own_base_and_openai_prefix() -> None:
    """国内供应商必须带上自己的 api_base，而不是落到 OpenAI。"""
    client = image_factory.create_client(_record(), None)
    target = client._target

    assert target.model == "openai/doubao-seedream-4-0-250828"
    assert target.api_base == "https://ark.cn-beijing.volces.com/api/v3"


def test_full_endpoint_is_reduced_to_base() -> None:
    """用户直接粘完整地址时，不能拼成 .../images/generations/images/generations。"""
    client = image_factory.create_client(
        _record(base_url="https://ark.cn-beijing.volces.com/api/v3/images/generations"),
        None,
    )
    assert client._target.api_base == "https://ark.cn-beijing.volces.com/api/v3"


async def test_generate_passes_params_and_decodes_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 24
    captured: dict[str, Any] = {}

    async def fake_image_generation(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(b64_json=base64.b64encode(png).decode(), url=None),
                SimpleNamespace(b64_json=base64.b64encode(png).decode(), url=None),
            ]
        )

    monkeypatch.setattr(image_factory.litellm, "aimage_generation", fake_image_generation)

    client = image_factory.create_client(_record(), None)
    images = await client.generate(prompt="雪山日出", size="2048x1152", count=2)

    assert captured["model"] == "openai/doubao-seedream-4-0-250828"
    assert captured["api_base"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert captured["size"] == "2048x1152"
    assert captured["n"] == 2
    assert len(images) == 2
    assert images[0].media_type == "image/png"
    assert images[0].data == png


async def test_upstream_error_becomes_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("invalid api key")

    monkeypatch.setattr(image_factory.litellm, "aimage_generation", boom)

    client = image_factory.create_client(_record(), None)
    with pytest.raises(image_factory.ImageGenerationError, match="invalid api key"):
        await client.generate(prompt="x", size="1024x1024", count=1)


async def test_upstream_error_does_not_leak_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游常把请求参数回显在异常里；这条字符串会进模型上下文并落 run，必须擦过。"""

    async def echo(**kwargs: Any) -> Any:
        secret = "sk-live0123456789ab"
        raise RuntimeError(f'upstream rejected {{"api_key": "{secret}"}} at ?api_key={secret}')

    monkeypatch.setattr(image_factory.litellm, "aimage_generation", echo)

    client = image_factory.create_client(_record(), None)
    with pytest.raises(image_factory.ImageGenerationError) as captured:
        await client.generate(prompt="x", size="1024x1024", count=1)

    assert "sk-live0123456789ab" not in str(captured.value)
    assert "upstream rejected" in str(captured.value)
