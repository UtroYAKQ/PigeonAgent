"""管理端模型探测：用假模型验证接口成功路径，不访问真实上游。"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from app.infra.providers.llm import ResolvedModel
from app.services.model import llm as model_service


class _FakeFactory:
    def __init__(self, _settings: Any) -> None:
        pass

    def create(self, record: Any, *, require_active: bool = True) -> ResolvedModel:
        assert require_active is False
        return ResolvedModel(
            name=record.name,
            model=TestModel(custom_output_text="OK"),
            settings={},
            context_window=None,
            supports_tools=True,
        )


async def _create_model(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/models",
        json={"name": "Probe Model", "provider": "openai", "model_name": "gpt-test"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_probe_model_reports_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_service, "ModelFactory", _FakeFactory)
    model = await _create_model(client)

    response = await client.post(f"/api/v1/models/{model['id']}/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["output"] == "OK"
    assert body["latency_ms"] >= 0
    assert body["error"] is None


async def test_probe_model_reports_configuration_error(client: AsyncClient) -> None:
    model = await _create_model(client)

    response = await client.post(f"/api/v1/models/{model['id']}/test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert "API key" in body["error"]
