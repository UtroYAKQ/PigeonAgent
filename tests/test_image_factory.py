from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.infra.providers import image as image_factory
from app.models.ai.image import ImageModel


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


async def test_generated_image_url_rejects_private_addresses() -> None:
    with pytest.raises(ValueError, match="非公网"):
        await image_factory._validate_remote_url("http://127.0.0.1/internal.png")
    with pytest.raises(ValueError, match="凭据"):
        await image_factory._validate_remote_url("https://user:pass@example.com/image.png")


async def test_generated_image_download_is_size_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_url(url: str) -> image_factory._RemoteTarget:
        return image_factory._RemoteTarget(url, "images.example", "images.example")

    monkeypatch.setattr(image_factory, "_validate_remote_url", allow_url)

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"x" * (image_factory.MAX_IMAGE_DOWNLOAD_BYTES + 1),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="大小上限"):
            await image_factory._download_remote_image(client, "https://images.example/test.png")


async def test_generated_image_redirect_is_revalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: list[str] = []

    async def validate(url: str) -> image_factory._RemoteTarget:
        checked.append(url)
        if "127.0.0.1" in url:
            raise ValueError("非公网")
        return image_factory._RemoteTarget(url, "images.example", "images.example")

    monkeypatch.setattr(image_factory, "_validate_remote_url", validate)

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/internal.png"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="非公网"):
            await image_factory._download_remote_image(client, "https://images.example/test.png")
    assert checked == [
        "https://images.example/test.png",
        "http://127.0.0.1/internal.png",
    ]


async def test_generated_image_connection_is_pinned_to_validated_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolve(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(image_factory.socket, "getaddrinfo", resolve)
    target = await image_factory._validate_remote_url(
        "https://images.example:8443/path/image.png?token=abc"
    )

    assert target.request_url == "https://93.184.216.34:8443/path/image.png?token=abc"
    assert target.host_header == "images.example:8443"
    assert target.sni_hostname == "images.example"
