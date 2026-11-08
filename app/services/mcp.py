"""管理员托管的 MCP 服务器：CRUD、选择校验与连通性测试。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.mcp import MCPToolset
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    UnprocessableError,
    describe_error,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.models.ai.mcp import McpServer
from app.schemas.mcp import (
    MAX_MCP_SERVERS,
    McpServerCreate,
    McpServerTestResult,
    McpServerUpdate,
    McpToolInfo,
)

logger = logging.getLogger(__name__)

# “测试连接”是管理端操作，不能无限等一个挂掉的上游
TEST_TIMEOUT_SECONDS = 20.0


def _encrypt_auth(auth: str | None, secret_key: str | None) -> str | None:
    value = (auth or "").strip()
    if not value:
        return None
    if secret_key is None:
        raise ConfigurationError("保存 MCP token 需要配置 SECRET_KEY")
    return encrypt_secret(value, secret_key)


def headers_for(server: McpServer, secret_key: str | None) -> dict[str, str]:
    if not server.auth_encrypted:
        return {}
    if secret_key is None:
        raise ConfigurationError("读取 MCP token 需要配置 SECRET_KEY")
    token = decrypt_secret(server.auth_encrypted, secret_key)
    return {"Authorization": f"Bearer {token}"}


async def list_servers(db: AsyncSession, *, limit: int, offset: int) -> tuple[list[McpServer], int]:
    total = int(await db.scalar(select(func.count()).select_from(McpServer)) or 0)
    servers = await db.scalars(
        select(McpServer).order_by(McpServer.name).offset(offset).limit(limit)
    )
    return list(servers), total


async def get_server_or_404(db: AsyncSession, server_id: UUID) -> McpServer:
    server = await db.get(McpServer, server_id)
    if server is None:
        raise NotFoundError(f"MCP server {server_id} not found")
    return server


async def list_enabled_options(db: AsyncSession) -> list[McpServer]:
    servers = await db.scalars(
        select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name)
    )
    return list(servers)


def _parse_ids(raw_ids: Sequence[UUID | str]) -> list[UUID]:
    parsed: list[UUID] = []
    for raw in raw_ids:
        try:
            value = UUID(str(raw))
        except (TypeError, ValueError):
            continue
        if value not in parsed:
            parsed.append(value)
    return parsed


async def resolve_enabled(db: AsyncSession, server_ids: Sequence[UUID | str]) -> list[McpServer]:
    """按会话里的顺序返回仍启用的服务器；已删除/停用的安静跳过。"""
    parsed = _parse_ids(server_ids)
    if not parsed:
        return []
    servers = await db.scalars(
        select(McpServer).where(
            McpServer.id.in_(parsed),
            McpServer.enabled.is_(True),
        )
    )
    by_id = {server.id: server for server in servers}
    return [by_id[server_id] for server_id in parsed if server_id in by_id]


async def validate_selection(db: AsyncSession, server_ids: list[UUID]) -> list[UUID]:
    """会话选择写入前校验：去重、限数、必须是已启用服务器。"""
    unique_ids = list(dict.fromkeys(server_ids))
    if len(unique_ids) > MAX_MCP_SERVERS:
        raise UnprocessableError(f"每个会话最多启用 {MAX_MCP_SERVERS} 个 MCP 服务器")
    if not unique_ids:
        return []
    servers = await db.scalars(select(McpServer).where(McpServer.id.in_(unique_ids)))
    by_id = {server.id: server for server in servers}
    missing = [server_id for server_id in unique_ids if server_id not in by_id]
    if missing:
        raise UnprocessableError("选中的 MCP 服务器不存在")
    disabled = [server_id for server_id in unique_ids if not by_id[server_id].enabled]
    if disabled:
        raise UnprocessableError("选中的 MCP 服务器已停用")
    return unique_ids


async def create_server(
    db: AsyncSession, payload: McpServerCreate, *, secret_key: str | None
) -> McpServer:
    values = payload.model_dump(exclude={"auth"})
    values["auth_encrypted"] = _encrypt_auth(
        payload.auth.get_secret_value() if payload.auth is not None else None,
        secret_key,
    )
    server = McpServer(**values)
    db.add(server)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("MCP 服务器名称或 slug 已存在") from exc
    await db.refresh(server)
    return server


async def update_server(
    db: AsyncSession,
    server_id: UUID,
    payload: McpServerUpdate,
    *,
    secret_key: str | None,
) -> McpServer:
    server = await get_server_or_404(db, server_id)
    data = payload.model_dump(exclude_unset=True, exclude={"auth"})
    if "auth" in payload.model_fields_set:
        auth = payload.auth.get_secret_value() if payload.auth is not None else None
        data["auth_encrypted"] = _encrypt_auth(auth, secret_key)
    for field_name, value in data.items():
        setattr(server, field_name, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("MCP 服务器名称或 slug 已存在") from exc
    await db.refresh(server)
    return server


async def delete_server(db: AsyncSession, server_id: UUID) -> None:
    server = await get_server_or_404(db, server_id)
    await db.delete(server)
    await db.commit()


def build_mcp_toolset(server: McpServer, *, settings: Settings) -> MCPToolset:
    """管理员测试连接和每轮装配共用同一份构造参数。"""
    headers = headers_for(server, settings.secret_key)
    return MCPToolset(
        server.url,
        headers=headers or None,
        init_timeout=10,
        read_timeout=float(server.timeout_seconds),
        tool_error_behavior="failed",
    )


async def test_connection(
    db: AsyncSession, server: McpServer, *, settings: Settings
) -> McpServerTestResult:
    """连一次 MCP 并列出工具；结果写回管理端缓存字段。"""
    server.last_checked_at = datetime.now(UTC)
    try:
        toolset = build_mcp_toolset(server, settings=settings)
        async with asyncio.timeout(TEST_TIMEOUT_SECONDS):
            async with toolset:
                tools = await toolset.client.list_tools()
        result = McpServerTestResult(
            ok=True,
            tools=[McpToolInfo(name=tool.name, description=tool.description) for tool in tools],
        )
        server.tool_count = len(result.tools)
    except Exception as exc:
        logger.warning("MCP server %s test failed: %s", server.slug, exc)
        result = McpServerTestResult(ok=False, error=describe_error(exc)[:500])
    await db.commit()
    await db.refresh(server)
    return result
