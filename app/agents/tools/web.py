"""DeepSeek Search / Fetch 工具：给模型提供实时网页搜索与正文抓取。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic_ai import Tool

from app.core.config import Settings
from app.core.exceptions import describe_error
from app.core.security.redaction import redact_text

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 128
MAX_URL_CHARS = 8192
MAX_SEARCH_RESULTS = 10
MAX_FETCH_CHARS = 30_000
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class WebToolError(RuntimeError):
    """搜索/抓取失败；只返回给模型，不把上游密钥带出去。"""


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message_value = error.get("message")
            if isinstance(message_value, str):
                message = message_value.strip()
                if message:
                    # 上游原文会原样进模型上下文，先按形态擦掉凭据
                    return redact_text(message)[:500]
    return f"DeepSeek 搜索服务返回 HTTP {response.status_code}"


async def _post_json(
    settings: Settings,
    path: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """带一次退避重试的 JSON POST；408/429/5xx 才重试，其余 4xx 直接报错。"""
    if not settings.deepseek_api_key:
        raise WebToolError("未配置 DEEPSEEK_API_KEY，联网搜索不可用")
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.deepseek_api_base.rstrip("/")
    last_error: str | None = None

    # 两次尝试共用一个连接池：重试时不必再付一次 TLS 握手
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds) as client:
        for attempt in range(2):
            try:
                response = await client.post(path, json=payload, headers=headers)
            except httpx.TimeoutException:
                last_error = "搜索服务请求超时"
            except httpx.HTTPError as exc:
                last_error = f"搜索服务连接失败：{exc.__class__.__name__}"
            else:
                if response.status_code == 200:
                    data = response.json()
                    if not isinstance(data, dict):
                        raise WebToolError("搜索服务返回了非 JSON 对象")
                    return data
                last_error = _error_message(response)
                if response.status_code not in RETRYABLE_STATUS:
                    raise WebToolError(last_error)

            if attempt == 0:
                await asyncio.sleep(0.6)

    raise WebToolError(last_error or "搜索服务不可用")


def _validate_query(query: str) -> str:
    value = query.strip()
    if not value:
        raise WebToolError("query 不能为空")
    if len(value) > MAX_QUERY_CHARS:
        raise WebToolError(f"query 不能超过 {MAX_QUERY_CHARS} 个字符")
    return value


def _validate_url(url: str) -> str:
    value = url.strip()
    if not value or len(value) > MAX_URL_CHARS:
        raise WebToolError(f"url 必须为 1~{MAX_URL_CHARS} 个字符")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebToolError("url 必须是带 host 的 http/https 地址")
    if parsed.username or parsed.password:
        raise WebToolError("url 不能携带用户名或密码")
    return value


def _normalize_search_results(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for raw in raw_results[:limit]:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title")
        url = raw.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        if not title.strip() or not url.strip():
            continue
        cleaned.append(
            {
                "title": title.strip()[:300],
                "url": url.strip(),
                "snippet": str(raw.get("snippet") or "")[:600],
                "summary": str(raw.get("summary") or "")[:1600],
                "site_name": raw.get("site_name"),
                "site_icon": raw.get("site_icon"),
                "date": raw.get("date"),
                "authority": raw.get("authority"),
                "rerank_score": raw.get("rerank_score"),
            }
        )
    return cleaned


class WebTools:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def web_search(self, query: str, count: int = 6) -> dict[str, Any]:
        """搜索实时网页，返回标题、链接和摘要，用于回答需要最新信息的问题。

        Args:
            query: 搜索词，支持 site:、-site:、引号等语法，最多 128 个字符。
            count: 返回条数，1~10，默认 6；不需要正文，需要正文时再调用 fetch_url。
        """
        try:
            cleaned_query = _validate_query(query)
            limit = max(1, min(int(count), MAX_SEARCH_RESULTS))
            data = await _post_json(
                self._settings,
                "/v1/tools/search",
                {"query": cleaned_query, "count": limit, "need_content": False},
                timeout_seconds=self._settings.deepseek_search_timeout_seconds,
            )
            results = _normalize_search_results(data, limit)
            return {"query": cleaned_query, "results": results, "total": len(results)}
        except (WebToolError, ValueError) as exc:
            logger.info("Web search failed: %s", exc)
            return {
                "query": str(query)[:MAX_QUERY_CHARS],
                "results": [],
                "error": describe_error(exc),
            }
        except Exception as exc:  # 工具失败要回给模型，不要打断整轮
            logger.exception("Unexpected web search failure")
            return {
                "query": str(query)[:MAX_QUERY_CHARS],
                "results": [],
                "error": describe_error(exc, include_type=True),
            }

    async def fetch_url(self, url: str) -> dict[str, Any]:
        """抓取单个网页，返回标题和 Markdown 正文，适合读取搜索结果详情。

        Args:
            url: 要抓取的 http/https 网页地址。
        """
        try:
            cleaned_url = _validate_url(url)
            data = await _post_json(
                self._settings,
                "/v1/tools/fetch",
                {"url": cleaned_url},
                timeout_seconds=self._settings.deepseek_fetch_timeout_seconds,
            )
            content = str(data.get("content") or "")
            if not content.strip():
                return {"url": cleaned_url, "error": "该页面没有可提取的正文"}
            if len(content) > MAX_FETCH_CHARS:
                content = content[:MAX_FETCH_CHARS] + "\n\n[正文过长，已截断]"
            title = str(data.get("title") or "")
            return {"url": cleaned_url, "title": title, "content": content}
        except WebToolError as exc:
            logger.info("Web fetch failed: %s", exc)
            return {"url": str(url)[:MAX_URL_CHARS], "error": describe_error(exc)}
        except Exception as exc:
            logger.exception("Unexpected web fetch failure")
            return {
                "url": str(url)[:MAX_URL_CHARS],
                "error": describe_error(exc, include_type=True),
            }


def web_search_tools(settings: Settings) -> list[Tool[Any]]:
    """联网工具的下发条件与能力下发同一条规则：凭证齐且总闸开着。"""
    if not settings.can_use_web_search:
        return []
    service = WebTools(settings)
    return [Tool(service.web_search), Tool(service.fetch_url)]
