import importlib
import inspect
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import Any

from pydantic_ai import ModelSettings
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, UnprocessableError
from app.core.security import decrypt_secret
from app.enums import LlmProvider
from app.models.llm_model import LlmModel

# ---------------------------------------------------------------- provider 映射
# 有专用 model 模块的 provider；其余一律走 OpenAI 兼容的 OpenAIChatModel
NATIVE_MODEL_MODULES = frozenset(
    {
        "anthropic",
        "bedrock",
        "bedrock_mantle",
        "cerebras",
        "cohere",
        "crusoe",
        "github_copilot",
        "google",
        "groq",
        "huggingface",
        "mistral",
        "openrouter",
        "snowflake",
        "system_one",
        "typesafe",
        "xai",
        "zai",
    }
)

# google_cloud 的 provider 独立，但 model 复用 google 模块
MODEL_MODULE_OVERRIDES = {"google_cloud": "google"}

# custom 走通用 OpenAI 兼容 provider，由 base_url 指定端点
PROVIDER_MODULE_OVERRIDES = {"custom": "openai"}

# 本地/自建部署可以完全没有鉴权
NO_API_KEY_REQUIRED = frozenset({"custom", "vllm"})

OPENAI_MODEL_MODULE = "openai"
OPENAI_MODEL_PATH = f"pydantic_ai.models.{OPENAI_MODEL_MODULE}"
PREFERRED_OPENAI_MODEL = "OpenAIChatModel"


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    name: str
    model: Model
    settings: ModelSettings
    context_window: int | None
    supports_tools: bool
    compaction_threshold: float | None = None


class ModelFactory:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create(self, record: LlmModel) -> ResolvedModel:
        if not record.is_active:
            raise UnprocessableError(f"Model '{record.name}' is not active")
        if record.provider == LlmProvider.CUSTOM.value and not record.base_url:
            raise UnprocessableError(
                f"Model '{record.name}' uses provider 'custom' but has no base_url"
            )

        provider = self._build_provider(
            record.provider,
            api_key=self._resolve_api_key(record),
            base_url=record.base_url,
        )
        model_settings: ModelSettings = {"timeout": self._settings.llm_timeout_seconds}
        if record.max_output_tokens is not None:
            model_settings["max_tokens"] = record.max_output_tokens
        return ResolvedModel(
            name=record.name,
            model=_model_class(record.provider)(record.model_name, provider=provider),
            settings=model_settings,
            context_window=record.context_window,
            supports_tools=record.supports_tools,
            compaction_threshold=record.compaction_threshold,
        )

    def _resolve_api_key(self, record: LlmModel) -> str | None:
        if record.api_key_encrypted:
            if self._settings.secret_key is None:
                raise ConfigurationError("SECRET_KEY is required to decrypt model API keys")
            return decrypt_secret(record.api_key_encrypted, self._settings.secret_key)
        if record.provider in NO_API_KEY_REQUIRED:
            return None
        raise UnprocessableError(f"Model '{record.name}' has no API key configured")

    def _build_provider(
        self, provider_name: str, *, api_key: str | None, base_url: str | None
    ) -> Any:
        provider_class = _provider_class(provider_name)

        params = inspect.signature(provider_class.__init__).parameters
        kwargs: dict[str, Any] = {}
        # 两个可选参数处理不对称：Bedrock 之类本就不收 api_key（走 IAM 凭证），丢了就丢；
        # base_url 被静默忽略会把流量打到厂商公网，管理员还以为走了自建网关，必须报错。
        if api_key is not None and "api_key" in params:
            kwargs["api_key"] = api_key
        if base_url is not None:
            if "base_url" not in params:
                raise ConfigurationError(
                    f"Provider '{provider_name}' does not accept base_url; "
                    "use provider 'custom' for self-hosted gateways"
                )
            kwargs["base_url"] = base_url
        try:
            return provider_class(**kwargs)
        except UserError as exc:
            raise ConfigurationError(
                f"Provider '{provider_name}' rejected the configuration: {exc}"
            ) from exc


def _import_module(module_name: str, provider_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigurationError(f"Provider '{provider_name}' is unavailable: {exc}") from exc


@cache
def _provider_class(provider_name: str) -> type[Any]:
    """模块导入与 vars 全量扫描只在首次解析，之后随进程缓存。"""
    module = _import_module(provider_module_name(provider_name), provider_name)
    return _resolve_class(module, "Provider", provider_name)


@cache
def _model_class(provider_name: str) -> type[Any]:
    module_path = model_module_name(provider_name)
    module = _import_module(module_path, provider_name)
    prefer = PREFERRED_OPENAI_MODEL if module_path == OPENAI_MODEL_PATH else None
    return _resolve_class(module, "Model", provider_name, prefer=prefer)


def provider_module_name(provider_name: str) -> str:
    short = PROVIDER_MODULE_OVERRIDES.get(provider_name, provider_name)
    return f"pydantic_ai.providers.{short}"


def model_module_name(provider_name: str) -> str:
    short = MODEL_MODULE_OVERRIDES.get(provider_name)
    if short is None:
        short = provider_name if provider_name in NATIVE_MODEL_MODULES else OPENAI_MODEL_MODULE
    return f"pydantic_ai.models.{short}"


def _resolve_class(
    module: ModuleType, suffix: str, provider_name: str, *, prefer: str | None = None
) -> type[Any]:
    label = f"provider '{provider_name}'"
    candidates = [
        (name, obj)
        for name, obj in vars(module).items()
        if inspect.isclass(obj)
        and name.endswith(suffix)
        and not name.startswith("_")
        and name not in {"Provider", "Model", "BaseModel"}
        and getattr(obj, "__module__", "") == module.__name__
    ]
    if not candidates:
        raise ConfigurationError(f"No {suffix.lower()} class found for {label}")
    if prefer is not None:
        for name, obj in candidates:
            if name == prefer:
                return obj
    if len(candidates) > 1:
        names = [name for name, _ in candidates]
        raise ConfigurationError(f"Ambiguous {suffix.lower()} class for {label}: {names}")
    return candidates[0][1]
