"""图片生成工厂：用 LiteLLM 统一调用各家的 OpenAI 兼容出图接口。

LiteLLM 负责协议差异（请求形状、返回 b64 还是 url、错误类型），这一层只做三件事：
挑出可用的模型配置、解密 key、把结果归一成 `GeneratedImage`。
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import litellm

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, UnprocessableError
from app.core.redaction import redact_text
from app.core.security import decrypt_secret
from app.domain.media_type import detect_media_type
from app.enums import ImageProvider
from app.infra.image_presets import preset_of, resolve_base_url
from app.models.image_model import ImageModel

logger = logging.getLogger(__name__)

# 出图普遍比对话慢，留足上游排队时间
GENERATION_TIMEOUT_SECONDS = 180.0
MAX_IMAGE_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_REDIRECTS = 5
# 没有 key 的内网网关也要求带一个非空值
_PLACEHOLDER_KEY = "sk-no-key"


class ImageGenerationError(RuntimeError):
    """生成失败；只把可读原因抛给工具层，不带出密钥。"""


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    media_type: str
    revised_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class _Target:
    model: str
    api_base: str
    api_key: str
    quality: str | None


@dataclass(frozen=True, slots=True)
class _RemoteTarget:
    request_url: str
    host_header: str
    sni_hostname: str


def _resolve_api_key(record: ImageModel, settings: Settings) -> str | None:
    if not record.api_key_encrypted:
        return None
    if settings.secret_key is None:
        raise ConfigurationError("SECRET_KEY is required to decrypt image model API keys")
    return decrypt_secret(record.api_key_encrypted, settings.secret_key)


def create_client(record: ImageModel, settings: Settings | None = None) -> ImageClient:
    if not record.is_active:
        raise UnprocessableError(f"Image model '{record.name}' is not active")
    if record.provider not in {provider.value for provider in ImageProvider}:
        raise ConfigurationError(f"Unsupported image provider '{record.provider}'")

    settings = settings or get_settings()
    try:
        api_base = resolve_base_url(record.provider, record.base_url)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    # 前缀就是 LiteLLM 的协议路由（openai/azure/bedrock/...），地址由 api_base 决定
    protocol = record.protocol or preset_of(record.provider).protocol.value
    return ImageClient(
        _Target(
            model=f"{protocol}/{record.model_name}",
            api_base=api_base,
            api_key=_resolve_api_key(record, settings) or _PLACEHOLDER_KEY,
            quality=record.quality,
        )
    )


class ImageClient:
    """一次生成调用；协议差异交给 LiteLLM。"""

    def __init__(self, target: _Target) -> None:
        self._target = target

    async def generate(self, *, prompt: str, size: str, count: int) -> list[GeneratedImage]:
        if not prompt.strip():
            raise ImageGenerationError("提示词不能为空")

        params: dict[str, object] = {
            "model": self._target.model,
            "prompt": prompt,
            "api_base": self._target.api_base,
            "api_key": self._target.api_key,
            "n": count,
            "size": size,
            "timeout": GENERATION_TIMEOUT_SECONDS,
            "num_retries": 1,
        }
        if self._target.quality:
            params["quality"] = self._target.quality

        try:
            response = await litellm.aimage_generation(**params)
        except Exception as exc:  # LiteLLM 会把上游错误包装成自己的异常族
            logger.warning("Image generation failed: %s", exc)
            raise ImageGenerationError(_readable_error(exc)) from exc

        items = getattr(response, "data", None) or []
        images: list[GeneratedImage] = []
        async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SECONDS) as client:
            for item in items:
                image = await _item_to_image(item, client)
                if image is not None:
                    images.append(image)
        if not images:
            raise ImageGenerationError("上游没有返回可用的图片")
        return images


async def _item_to_image(item: object, client: httpx.AsyncClient) -> GeneratedImage | None:
    """供应商可能给 base64，也可能给一段临时 url，两种都收。"""
    revised = getattr(item, "revised_prompt", None)
    revised_prompt = revised if isinstance(revised, str) else None

    encoded = getattr(item, "b64_json", None)
    if isinstance(encoded, str) and encoded:
        try:
            raw = base64.b64decode(encoded)
        except ValueError:
            logger.warning("Upstream returned invalid base64 image data")
            return None
        return GeneratedImage(raw, _sniff_media_type(raw), revised_prompt)

    url = getattr(item, "url", None)
    if isinstance(url, str) and url:
        try:
            raw, media_type = await _download_remote_image(client, url)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Download generated image failed: %s", exc.__class__.__name__)
            return None
        return GeneratedImage(raw, media_type, revised_prompt)

    return None


async def _download_remote_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    """逐跳校验供应商 URL，并在读取过程中执行硬字节上限。"""
    current = url
    for redirect_count in range(MAX_IMAGE_REDIRECTS + 1):
        target = await _validate_remote_url(current)
        async with client.stream(
            "GET",
            target.request_url,
            follow_redirects=False,
            headers={"Host": target.host_header},
            extensions={"sni_hostname": target.sni_hostname},
        ) as response:
            if response.is_redirect:
                if redirect_count >= MAX_IMAGE_REDIRECTS:
                    raise ValueError("too many image redirects")
                location = response.headers.get("location")
                if not location:
                    raise ValueError("image redirect has no location")
                current = urljoin(current, location)
                continue

            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise ValueError("invalid image content-length") from exc
                if declared_size > MAX_IMAGE_DOWNLOAD_BYTES:
                    raise ValueError("generated image is too large")

            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_IMAGE_DOWNLOAD_BYTES:
                    raise ValueError("generated image is too large")
                body.extend(chunk)
            media_type = response.headers.get("content-type", "")
            normalized = media_type.split(";", 1)[0].strip()
            if not normalized.startswith("image/"):
                normalized = _sniff_media_type(bytes(body))
            return bytes(body), normalized
    raise ValueError("too many image redirects")


async def _validate_remote_url(url: str) -> _RemoteTarget:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("generated image URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("generated image URL must not contain credentials")
    host = parsed.hostname
    if not host:
        raise ValueError("generated image URL has no host")
    ascii_host = host.encode("idna").decode("ascii")

    try:
        addresses = [ipaddress.ip_address(ascii_host)]
    except ValueError:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            results = await asyncio.to_thread(
                socket.getaddrinfo, ascii_host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise ValueError("generated image host cannot be resolved") from exc
        addresses = list({ipaddress.ip_address(item[4][0]) for item in results})

    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("generated image URL resolves to a non-public address")
    selected = sorted(addresses, key=lambda address: (address.version, address.packed))[0]
    pinned_host = f"[{selected.compressed}]" if selected.version == 6 else selected.compressed
    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    request_url = urlunsplit(
        (
            parsed.scheme,
            f"{pinned_host}{port_suffix}",
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    host_header = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    return _RemoteTarget(
        request_url=request_url,
        host_header=f"{host_header}{port_suffix}",
        sni_hostname=ascii_host,
    )


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _sniff_media_type(data: bytes) -> str:
    detected = detect_media_type(None, data)
    return detected if detected.startswith("image/") else "image/png"


def _readable_error(exc: Exception) -> str:
    """LiteLLM 的异常消息里通常已经带了上游原文，取第一条可用信息即可。

    上游原文会回显请求参数（含 api_key），所以先擦凭据再截断——这条字符串
    会进模型上下文并落 run 内容，管理员侧可读。
    """
    message = redact_text(str(exc).strip())
    if message:
        return message[:500]
    return f"生成失败：{exc.__class__.__name__}"
