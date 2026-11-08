from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUserDep, SessionDep, SettingsDep
from app.models.ai.mcp import McpServer
from app.schemas.mcp import (
    McpServerCreate,
    McpServerList,
    McpServerRead,
    McpServerTestResult,
    McpServerUpdate,
)
from app.services import mcp as mcp_service
from app.services.admin import audit

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])


@router.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_server(
    payload: McpServerCreate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> McpServer:
    server = await mcp_service.create_server(db, payload, secret_key=settings.secret_key)
    await audit.record(
        actor=user,
        action=audit.MCP_SERVER_CREATE,
        target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "slug": server.slug},
    )
    return server


@router.get("", response_model=McpServerList)
async def list_servers(
    db: SessionDep,
    user: AdminUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> McpServerList:
    servers, total = await mcp_service.list_servers(db, limit=limit, offset=offset)
    return McpServerList(
        items=[McpServerRead.model_validate(server) for server in servers],
        total=total,
    )


@router.get("/{server_id}", response_model=McpServerRead)
async def get_server(server_id: UUID, db: SessionDep, user: AdminUserDep) -> McpServer:
    return await mcp_service.get_server_or_404(db, server_id)


@router.patch("/{server_id}", response_model=McpServerRead)
async def update_server(
    server_id: UUID,
    payload: McpServerUpdate,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> McpServer:
    server = await mcp_service.update_server(db, server_id, payload, secret_key=settings.secret_key)
    await audit.record(
        actor=user,
        action=audit.MCP_SERVER_UPDATE,
        target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "slug": server.slug},
    )
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: UUID, db: SessionDep, user: AdminUserDep) -> None:
    server = await mcp_service.get_server_or_404(db, server_id)
    name = server.name
    await mcp_service.delete_server(db, server_id)
    await audit.record(
        actor=user,
        action=audit.MCP_SERVER_DELETE,
        target_type="mcp_server",
        target_id=str(server_id),
        detail={"name": name},
    )


@router.post("/{server_id}/test", response_model=McpServerTestResult)
async def test_server(
    server_id: UUID,
    db: SessionDep,
    settings: SettingsDep,
    user: AdminUserDep,
) -> McpServerTestResult:
    server = await mcp_service.get_server_or_404(db, server_id)
    result = await mcp_service.test_connection(db, server, settings=settings)
    await audit.record(
        actor=user,
        action=audit.MCP_SERVER_TEST,
        target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "ok": result.ok, "tool_count": len(result.tools)},
    )
    return result
