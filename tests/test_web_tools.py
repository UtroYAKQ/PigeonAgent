from __future__ import annotations

import pytest

from app.agents.tools import web as web_module
from app.agents.tools.web import WebToolError, WebTools, _normalize_search_results, _validate_url
from app.core.config import Settings


def settings_with_key() -> Settings:
    return Settings(deepseek_api_key="test-key", deepseek_api_base="https://api.deepseek.test")


def test_web_search_tools_absent_without_key() -> None:
    assert web_module.web_search_tools(Settings(deepseek_api_key=None)) == []


def test_web_search_tools_available_with_key() -> None:
    tools = web_module.web_search_tools(settings_with_key())
    assert [tool.name for tool in tools] == ["web_search", "fetch_url"]


def test_validate_url_rejects_unsafe_values() -> None:
    with pytest.raises(WebToolError):
        _validate_url("file:///tmp/a.html")
    with pytest.raises(WebToolError):
        _validate_url("https://user:pass@example.com/a")


def test_normalize_search_results_trims_and_skips_invalid() -> None:
    results = _normalize_search_results(
        {
            "results": [
                {
                    "title": "标题",
                    "url": "https://example.com",
                    "snippet": "摘要",
                    "summary": "长摘要",
                    "site_name": "示例",
                },
                {"title": "", "url": "https://bad.example"},
                "not-an-object",
            ]
        },
        limit=5,
    )
    assert results == [
        {
            "title": "标题",
            "url": "https://example.com",
            "snippet": "摘要",
            "summary": "长摘要",
            "site_name": "示例",
            "site_icon": None,
            "date": None,
            "authority": None,
            "rerank_score": None,
        }
    ]


async def test_web_search_calls_deepseek_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(
        settings: Settings,
        path: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        assert path == "/v1/tools/search"
        assert payload["query"] == "杭州天气"
        assert timeout_seconds == 20.0
        return {
            "results": [
                {
                    "title": "杭州天气",
                    "url": "https://weather.example/hz",
                    "snippet": "多云",
                    "summary": "今天多云。",
                }
            ]
        }

    monkeypatch.setattr(web_module, "_post_json", fake_post)
    result = await WebTools(settings_with_key()).web_search("杭州天气", count=99)
    assert result["total"] == 1
    assert result["results"][0]["url"] == "https://weather.example/hz"


async def test_web_search_returns_error_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(*args: object, **kwargs: object) -> dict[str, object]:
        raise WebToolError("额度不足")

    monkeypatch.setattr(web_module, "_post_json", fake_post)
    result = await WebTools(settings_with_key()).web_search("test")
    assert result["results"] == []
    assert result["error"] == "额度不足"


def test_normalize_search_results_caps_summary_and_snippet() -> None:
    [result] = _normalize_search_results(
        {
            "results": [
                {
                    "title": "t",
                    "url": "https://example.com",
                    "snippet": "s" * 900,
                    "summary": "m" * 900,
                }
            ]
        },
        limit=1,
    )
    assert len(result["snippet"]) == 400
    assert len(result["summary"]) == 800


async def test_fetch_url_honors_max_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(*args: object, **kwargs: object) -> dict[str, object]:
        return {"title": "长页面", "content": "x" * 5_000}

    monkeypatch.setattr(web_module, "_post_json", fake_post)
    result = await WebTools(settings_with_key()).fetch_url("https://example.com", max_chars=1_200)
    assert len(result["content"]) < 1_300
    assert result["content"].endswith("[正文过长，已截断]")


async def test_fetch_url_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(
        settings: Settings,
        path: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        assert path == "/v1/tools/fetch"
        assert payload["url"] == "https://example.com"
        return {"title": "示例页面", "content": "# 正文"}

    monkeypatch.setattr(web_module, "_post_json", fake_post)
    result = await WebTools(settings_with_key()).fetch_url("https://example.com")
    assert result == {"url": "https://example.com", "title": "示例页面", "content": "# 正文"}
