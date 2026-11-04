from __future__ import annotations

import pytest

from app.core.exceptions import UnprocessableError
from app.infra.image_presets import resolve_endpoint


def test_openai_uses_its_own_base_url() -> None:
    assert resolve_endpoint("openai", None) == "https://api.openai.com/v1/images/generations"


def test_cn_providers_do_not_fall_back_to_openai() -> None:
    """换了供应商就必须换地址，不能沿用 OpenAI 的默认值。"""
    assert (
        resolve_endpoint("ark", None)
        == "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    )
    assert (
        resolve_endpoint("zhipu", None) == "https://open.bigmodel.cn/api/paas/v4/images/generations"
    )
    assert (
        resolve_endpoint("siliconflow", None) == "https://api.siliconflow.cn/v1/images/generations"
    )


def test_custom_base_url_overrides_preset() -> None:
    assert (
        resolve_endpoint("ark", "https://gateway.example.com/v1")
        == "https://gateway.example.com/v1/images/generations"
    )


def test_trailing_slash_is_ignored() -> None:
    assert (
        resolve_endpoint("openai", "https://api.openai.com/v1/")
        == "https://api.openai.com/v1/images/generations"
    )


def test_full_endpoint_is_not_suffixed_twice() -> None:
    full = "https://api.openai.com/v1/images/generations"
    assert resolve_endpoint("openai", full) == full


def test_custom_provider_requires_an_address() -> None:
    # 报 422 而不是 ValueError：管理员保存/试运行时要看到这句话，而不是一个 500
    with pytest.raises(UnprocessableError):
        resolve_endpoint("custom", None)
