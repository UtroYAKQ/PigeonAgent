"""操作日志：异步落库、参数/结果采集与敏感字段脱敏。"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from app.core.config import Settings
from app.tasks.operation_log import OperationLogger, _json_body, scrub
from tests.conftest import TEST_USER_EMAIL


def _by_path(items: list[dict[str, Any]], path: str, method: str) -> dict[str, Any]:
    for item in items:
        if item["path"] == path and item["method"] == method:
            return item
    raise AssertionError(f"未找到 {method} {path} 的日志：{items}")


async def test_requests_are_logged_with_params_and_results(client: AsyncClient) -> None:
    created = await client.post("/api/v1/sessions", json={"title": "操作日志"})
    assert created.status_code == 201, created.text
    await client.get("/api/v1/sessions", params={"q": "操作日志"})

    response = await client.get(
        "/api/v1/admin/logs",
        params={"q": "/api/v1/sessions", "limit": 50},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]

    post_log = _by_path(items, "/api/v1/sessions", "POST")
    assert post_log["kind"] == "request"
    assert post_log["actor_email"] == TEST_USER_EMAIL
    assert post_log["status_code"] == 201
    assert post_log["request_body"] == {"title": "操作日志"}
    assert post_log["response_body"]["title"] == "操作日志"
    assert post_log["duration_ms"] >= 0

    get_log = next(
        item for item in items if item["method"] == "GET" and item["path"] == "/api/v1/sessions"
    )
    assert get_log["query"]["q"] == "操作日志"


async def test_login_tokens_and_password_are_redacted(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": TEST_USER_EMAIL, "password": "pigeon-password"},
    )
    assert login.status_code == 200, login.text

    response = await client.get(
        "/api/v1/admin/logs",
        params={"q": "/api/v1/auth/login"},
    )
    items = response.json()["items"]
    login_log = _by_path(items, "/api/v1/auth/login", "POST")
    assert login_log["request_body"]["password"] == "***"
    assert login_log["response_body"]["access_token"] == "***"
    assert login_log["response_body"]["refresh_token"] == "***"


async def test_secret_config_value_is_redacted_in_request_log(
    client: AsyncClient,
) -> None:
    updated = await client.patch(
        "/api/v1/configs/deepseek_api_key",
        json={"value": "sk-test-secret"},
    )
    assert updated.status_code == 200, updated.text

    response = await client.get(
        "/api/v1/admin/logs",
        params={"q": "/api/v1/configs/deepseek_api_key"},
    )
    items = response.json()["items"]
    log = _by_path(items, "/api/v1/configs/deepseek_api_key", "PATCH")
    assert log["request_body"]["value"] == "***"


def test_exclude_paths_support_wildcards() -> None:
    logger = OperationLogger(
        None,  # type: ignore[arg-type]
        Settings(
            operation_log_enabled=True,
            operation_log_exclude_paths="/api/v1/files/*/link,/api/v1/health",
        ),
    )
    assert not logger.should_log("/api/v1/files/abc/link")
    assert not logger.should_log("/api/v1/health")
    assert not logger.should_log("/api/v1/health/deep")
    assert logger.should_log("/api/v1/files/abc/content")


def test_raw_body_preview_is_redacted_too() -> None:
    """截断的 body 和非 JSON 的 body 没有 key 名可依，必须按形态擦掉凭据。"""
    truncated = _json_body(b'{"api_key": "sk-abcdefghij012345", "note": "ok"}', truncated=True)
    assert "sk-abcdefghij012345" not in str(truncated)
    assert truncated["_truncated"] is True

    plain = _json_body(b"Authorization: Bearer abcdef123456789", truncated=False)
    assert "abcdef123456789" not in plain


def test_scrub_redacts_nested_secrets_but_keeps_usage_fields() -> None:
    cleaned = scrub(
        {
            "password": "plain",
            "nested": {"refresh_token": "secret", "api_key": "key"},
            "total_tokens": 12,
            "items": [{"new_password": "x"}, {"value": 1}],
        }
    )
    assert cleaned["password"] == "***"
    assert cleaned["nested"]["refresh_token"] == "***"
    assert cleaned["nested"]["api_key"] == "***"
    assert cleaned["total_tokens"] == 12
    assert cleaned["items"][0]["new_password"] == "***"

    validation = scrub([{"loc": ["body", "password"], "msg": "too short", "input": "plain-secret"}])
    assert validation[0]["input"] == "***"
