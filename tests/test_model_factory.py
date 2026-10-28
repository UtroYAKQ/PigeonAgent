import importlib
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, UnprocessableError
from app.core.security import encrypt_secret
from app.enums import LlmProvider
from app.models.llm_model import LlmModel
from app.services.model_factory import (
    ModelFactory,
    model_module_name,
    provider_module_name,
)

SECRET_KEY = Fernet.generate_key().decode()


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"secret_key": SECRET_KEY, "llm_timeout_seconds": 30.0}
    values.update(overrides)
    return Settings(**values)


def make_record(**overrides: Any) -> LlmModel:
    values: dict[str, Any] = {
        "name": "gpt",
        "provider": LlmProvider.OPENAI.value,
        "model_name": "gpt-4.1",
        "api_key_encrypted": encrypt_secret("sk-test", SECRET_KEY),
        "context_window": 128000,
        "max_output_tokens": 4096,
        "supports_tools": True,
        "is_active": True,
        "is_default": False,
    }
    values.update(overrides)
    return LlmModel(**values)


def test_create_openai_model() -> None:
    resolved = ModelFactory(make_settings()).create(make_record())

    assert resolved.name == "gpt"
    assert isinstance(resolved.model, OpenAIChatModel)
    assert resolved.model.model_name == "gpt-4.1"
    provider = resolved.model.provider
    assert isinstance(provider, OpenAIProvider)
    assert provider.client.api_key == "sk-test"
    assert resolved.settings["max_tokens"] == 4096
    assert resolved.settings["timeout"] == 30.0
    assert resolved.context_window == 128000
    assert resolved.supports_tools is True


def test_deepseek_uses_its_own_provider_and_endpoint() -> None:
    record = make_record(provider=LlmProvider.DEEPSEEK.value, model_name="deepseek-chat")

    resolved = ModelFactory(make_settings()).create(record)

    provider = resolved.model.provider
    assert isinstance(provider, DeepSeekProvider)
    assert "deepseek" in str(provider.client.base_url)


def test_base_url_override_rejected_when_provider_does_not_accept_it() -> None:
    record = make_record(
        provider=LlmProvider.DEEPSEEK.value,
        model_name="deepseek-chat",
        base_url="https://proxy.example/v1",
    )

    with pytest.raises(ConfigurationError, match="does not accept base_url"):
        ModelFactory(make_settings()).create(record)


def test_custom_provider_requires_base_url() -> None:
    with pytest.raises(UnprocessableError, match="base_url"):
        ModelFactory(make_settings()).create(make_record(provider=LlmProvider.CUSTOM.value))


def test_custom_provider_builds_with_base_url() -> None:
    record = make_record(
        provider=LlmProvider.CUSTOM.value,
        base_url="http://localhost:8000/v1",
        api_key_encrypted=None,
    )

    resolved = ModelFactory(make_settings()).create(record)

    assert isinstance(resolved.model, OpenAIChatModel)
    provider = resolved.model.provider
    assert isinstance(provider, OpenAIProvider)
    assert str(provider.client.base_url).startswith("http://localhost:8000/v1")


def test_inactive_model_is_rejected() -> None:
    with pytest.raises(UnprocessableError, match="not active"):
        ModelFactory(make_settings()).create(make_record(is_active=False))


def test_missing_api_key_is_rejected() -> None:
    with pytest.raises(UnprocessableError, match="no API key"):
        ModelFactory(make_settings()).create(make_record(api_key_encrypted=None))


def test_missing_secret_key_is_reported() -> None:
    factory = ModelFactory(make_settings(secret_key=None))

    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        factory.create(make_record())


def test_wrong_secret_key_fails_to_decrypt() -> None:
    record = make_record(
        api_key_encrypted=encrypt_secret("sk-test", Fernet.generate_key().decode())
    )

    with pytest.raises(ConfigurationError, match="decrypt"):
        ModelFactory(make_settings()).create(record)


def test_missing_extra_names_the_package_to_install() -> None:
    record = make_record(provider=LlmProvider.ANTHROPIC.value, model_name="claude-sonnet-4-5")

    with pytest.raises(ConfigurationError, match="anthropic"):
        ModelFactory(make_settings()).create(record)


def test_every_provider_maps_to_a_real_module() -> None:
    for provider in LlmProvider:
        for module_name in (
            provider_module_name(provider.value),
            model_module_name(provider.value),
        ):
            try:
                importlib.import_module(module_name)
            except ImportError as exc:
                # 只允许"缺少可选依赖"，模块路径写错会报 No module named
                assert "install" in str(exc).lower(), f"{provider.value} -> {module_name}: {exc}"
