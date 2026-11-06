from __future__ import annotations

import pytest

from app.core.exceptions import UnprocessableError
from app.infra.image_presets import resolve_base_url


def test_openai_uses_its_own_base_url() -> None:
    assert resolve_base_url("openai", None) == "https://api.openai.com/v1"


def test_cn_providers_do_not_fall_back_to_openai() -> None:
    """换了供应商就必须换地址，不能沿用 OpenAI 的默认值。"""
    assert resolve_base_url("ark", None) == "https://ark.cn-beijing.volces.com/api/v3"
    assert resolve_base_url("zhipu", None) == "https://open.bigmodel.cn/api/paas/v4"
    assert resolve_base_url("siliconflow", None) == "https://api.siliconflow.cn/v1"


def test_custom_base_url_overrides_preset() -> None:
    assert (
        resolve_base_url("ark", "https://gateway.example.com/v1")
        == "https://gateway.example.com/v1"
    )


def test_trailing_slash_is_ignored() -> None:
    assert resolve_base_url("openai", "https://api.openai.com/v1/") == "https://api.openai.com/v1"


def test_full_endpoint_is_reduced_to_base() -> None:
    """直接把文档里的全路径粘进来时，交给 SDK 前要把路径后缀剥掉。"""
    full = "https://api.openai.com/v1/images/generations"
    assert resolve_base_url("openai", full) == "https://api.openai.com/v1"


def test_custom_provider_requires_an_address() -> None:
    # 报 422 而不是 ValueError：管理员保存/试运行时要看到这句话，而不是一个 500
    with pytest.raises(UnprocessableError):
        resolve_base_url("custom", None)
