"""图片生成工厂：用 LiteLLM 统一调用各家的 OpenAI 兼容出图接口。

LiteLLM 负责协议差异（请求形状、返回 b64 还是 url、错误类型），这一层只做三件事：
挑出可用的模型配置、解密 key、把结果归一成 `GeneratedImage`。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx
import litellm

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, UnprocessableError
from app.core.redaction import redact_text
from app.core.security import decrypt_secret
from app.enums import ImageProvider
from app.infra.image_presets import preset_of, resolve_base_url
from app.models.image_model import ImageModel

logger = logging.getLogger(__name__)

# 出图普遍比对话慢，留足上游排队时间
GENERATION_TIMEOUT_SECONDS = 180.0
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
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Download generated image failed: %s", exc.__class__.__name__)
            return None
        media_type = response.headers.get("content-type", "image/png").split(";")[0].strip()
        return GeneratedImage(response.content, media_type or "image/png", revised_prompt)

    return None


def _sniff_media_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _readable_error(exc: Exception) -> str:
    """LiteLLM 的异常消息里通常已经带了上游原文，取第一条可用信息即可。

    上游原文会回显请求参数（含 api_key），所以先擦凭据再截断——这条字符串
    会进模型上下文并落 run 内容，管理员侧可读。
    """
    message = redact_text(str(exc).strip())
    if message:
        return message[:500]
    return f"生成失败：{exc.__class__.__name__}"
