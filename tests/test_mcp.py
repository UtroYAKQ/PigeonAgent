"""管理员托管 MCP：CRUD、会话选择、工具装配与按需加载状态回放。"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic_ai._tool_search import ToolSearchCallPart, ToolSearchReturnPart
from pydantic_ai.toolsets import ApprovalRequiredToolset
from pydantic_ai.toolsets._tool_search import parse_discovered_tools
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import mcp as mcp_tools
from app.codec.items import items_from_response_part, tool_result_item
from app.codec.messages import messages_from_items
from app.core.config import Settings
from app.core.security import encrypt_secret
from app.models.ai.mcp import McpServer
from app.services import mcp as mcp_service
from tests.conftest import TEST_SECRET_KEY

SAMPLE = {
    "name": "GitHub",
    "slug": "github",
    "url": "https://mcp.example.com/mcp",
    "description": "代码托管",
    "auth": "test-token",
    "requires_approval": True,
    "defer_loading": True,
}


async def _create_server(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/mcp-servers", json={**SAMPLE, **overrides})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _create_session(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/v1/sessions", json={"title": "MCP 会话"})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_admin_crud_keeps_token_write_only(client: AsyncClient) -> None:
    created = await _create_server(client)
    assert created["has_auth"] is True
    assert "auth" not in created
    assert "auth_encrypted" not in created

    listing = await client.get("/api/v1/mcp-servers")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1

    updated = await client.patch(
        f"/api/v1/mcp-servers/{created['id']}",
        json={"name": "GitHub 企业版", "enabled": False, "requires_approval": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "GitHub 企业版"
    assert updated.json()["enabled"] is False
    assert updated.json()["requires_approval"] is False
    assert updated.json()["has_auth"] is True

    deleted = await client.delete(f"/api/v1/mcp-servers/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/mcp-servers")).json()["total"] == 0


async def test_admin_can_clear_and_replace_token(client: AsyncClient) -> None:
    created = await _create_server(client)

    cleared = await client.patch(f"/api/v1/mcp-servers/{created['id']}", json={"auth": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["has_auth"] is False

    replaced = await client.patch(
        f"/api/v1/mcp-servers/{created['id']}", json={"auth": "new-token"}
    )
    assert replaced.status_code == 200
    assert replaced.json()["has_auth"] is True

    kept = await client.patch(f"/api/v1/mcp-servers/{created['id']}", json={"name": "Renamed"})
    assert kept.status_code == 200
    assert kept.json()["has_auth"] is True


async def test_member_cannot_manage_mcp_servers(client: AsyncClient) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "mcp-member@example.com", "password": "member-password"},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

    response = await client.get("/api/v1/mcp-servers", headers=headers)
    assert response.status_code == 403


async def test_capabilities_only_expose_enabled_servers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    enabled = await _create_server(client)
    disabled = await _create_server(client, name="Retired", slug="retired", enabled=False)

    body = (await client.get("/api/v1/capabilities")).json()
    assert body["max_mcp_servers"] == 5
    names = [item["name"] for item in body["mcp_servers"]]
    assert names == [enabled["name"]]
    assert disabled["name"] not in names
    option = body["mcp_servers"][0]
    assert "url" not in option
    assert "has_auth" not in option
    assert option["defer_loading"] is True


async def test_session_selects_and_clears_mcp_servers(client: AsyncClient) -> None:
    first = await _create_server(client)
    second = await _create_server(client, name="Sentry", slug="sentry")
    session = await _create_session(client)

    selected = await client.patch(
        f"/api/v1/sessions/{session['id']}",
        json={"mcp_server_ids": [first["id"], second["id"], first["id"]]},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["mcp_server_ids"] == [first["id"], second["id"]]

    cleared = await client.patch(f"/api/v1/sessions/{session['id']}", json={"mcp_server_ids": []})
    assert cleared.status_code == 200
    assert cleared.json()["mcp_server_ids"] == []


async def test_session_rejects_unknown_disabled_or_too_many_servers(
    client: AsyncClient,
) -> None:
    session = await _create_session(client)
    unknown = await client.patch(
        f"/api/v1/sessions/{session['id']}",
        json={"mcp_server_ids": [str(uuid4())]},
    )
    assert unknown.status_code == 422

    disabled = await _create_server(client, enabled=False)
    rejected = await client.patch(
        f"/api/v1/sessions/{session['id']}",
        json={"mcp_server_ids": [disabled["id"]]},
    )
    assert rejected.status_code == 422

    created = []
    for index in range(6):
        created.append(await _create_server(client, name=f"Server {index}", slug=f"server_{index}"))
    too_many = await client.patch(
        f"/api/v1/sessions/{session['id']}",
        json={"mcp_server_ids": [item["id"] for item in created]},
    )
    assert too_many.status_code == 422


def _server(**overrides: Any) -> McpServer:
    values: dict[str, Any] = {
        "id": uuid4(),
        "name": "GitHub",
        "slug": "github",
        "url": "https://mcp.example.com/mcp",
        "enabled": True,
        "requires_approval": True,
        "defer_loading": True,
        "timeout_seconds": 120,
        "tool_count": 0,
        "auth_encrypted": encrypt_secret("test-token", TEST_SECRET_KEY),
    }
    values.update(overrides)
    return McpServer(**values)


class _FakeMCPToolset:
    def __init__(self, url: str, **kwargs: Any) -> None:
        self.url = url
        self.kwargs = kwargs
        self.prefix: str | None = None
        self.deferred = False

    def prefixed(self, prefix: str) -> _FakeMCPToolset:
        self.prefix = prefix
        return self

    def defer_loading(self) -> _FakeMCPToolset:
        self.deferred = True
        return self


def test_build_mcp_toolsets_prefixes_auth_and_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_service, "MCPToolset", _FakeMCPToolset)
    settings = Settings(_env_file=None, secret_key=TEST_SECRET_KEY)

    setup = mcp_tools.build_mcp_setup([_server()], settings=settings)

    assert len(setup.toolsets) == 1
    assert len(setup.servers) == 1
    assert setup.instructions and "search_tools" in setup.instructions
    resilient = setup.toolsets[0]
    approval = resilient.wrapped
    fake = approval.wrapped
    assert isinstance(approval, ApprovalRequiredToolset)
    assert isinstance(fake, _FakeMCPToolset)
    assert fake.url == "https://mcp.example.com/mcp"
    assert fake.kwargs["headers"] == {"Authorization": "Bearer test-token"}
    assert fake.prefix == "mcp_github_"
    assert fake.deferred is True


def test_build_mcp_toolsets_can_skip_approval_and_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_service, "MCPToolset", _FakeMCPToolset)
    settings = Settings(_env_file=None, secret_key=TEST_SECRET_KEY)
    server = _server(requires_approval=False, defer_loading=False, auth_encrypted=None)

    setup = mcp_tools.build_mcp_setup([server], settings=settings)

    assert setup.instructions and "直接调用" in setup.instructions
    fake = setup.toolsets[0].wrapped
    assert isinstance(fake, _FakeMCPToolset)
    assert fake.deferred is False
    assert fake.kwargs["headers"] is None


def test_build_mcp_setup_skips_servers_with_bad_credentials() -> None:
    settings = Settings(_env_file=None, secret_key=TEST_SECRET_KEY)
    server = _server(auth_encrypted="not-a-valid-token")

    setup = mcp_tools.build_mcp_setup([server], settings=settings)

    assert setup.servers == []
    assert setup.toolsets == []
    assert setup.instructions is None


def test_tool_search_state_survives_history_roundtrip() -> None:
    call = ToolSearchCallPart(args={"queries": ["github"]}, tool_call_id="call-1")
    call_items = items_from_response_part(call)
    assert call_items and call_items[0].display is True
    assert call_items[0].tool_kind == "tool-search"

    part = ToolSearchReturnPart(
        content={"discovered_tools": [{"name": "mcp_github__get_me"}]},
        tool_call_id="call-1",
    )
    result = tool_result_item(part)
    assert result.display is True
    assert result.tool_kind == "tool-search"

    messages = messages_from_items([*call_items, result])
    assert isinstance(messages[0].parts[0], ToolSearchCallPart)
    assert isinstance(messages[1].parts[0], ToolSearchReturnPart)
    assert parse_discovered_tools(messages) == {"mcp_github__get_me"}


async def test_new_session_can_select_mcp_before_first_message(
    client: AsyncClient,
) -> None:
    server = await _create_server(client)
    response = await client.post(
        "/api/v1/sessions",
        json={"title": "新会话", "mcp_server_ids": [server["id"]]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["mcp_server_ids"] == [server["id"]]


async def test_session_read_exposes_uuid_list(client: AsyncClient) -> None:
    server = await _create_server(client)
    session = await _create_session(client)
    updated = await client.patch(
        f"/api/v1/sessions/{session['id']}",
        json={"mcp_server_ids": [server["id"]]},
    )
    assert updated.status_code == 200
    assert UUID(updated.json()["mcp_server_ids"][0]) == UUID(server["id"])
