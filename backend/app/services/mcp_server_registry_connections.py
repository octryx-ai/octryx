"""Runtime side of a registered MCP server: connect, disconnect, delete, list its tools."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.security.compliance_audit import (
    AUDIT_CONNECTOR_ACCESS,
    OUTCOME_ALLOWED,
    OUTCOME_BLOCKED,
)
from .mcp_audit_vocabulary import (
    ACTION_CONNECTED,
    ACTION_CONNECTION_FAILED,
    ACTION_DELETED,
    ACTION_DISCONNECTED,
    BLOCK_RUNTIME_NAME_CONFLICT,
    connect_blocked,
)
from .mcp_server_registry import _audit_change, get_scoped_registration, mcp_server_readiness
from .mcp_server_registry_config import registration_is_connected, runtime_registration_id


async def connect_mcp_server(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    catalog: dict[str, dict[str, Any]],
    actor_user_id: str | None,
    mcp_client_manager: Any,
) -> dict[str, Any]:
    registration, readiness = await mcp_server_readiness(
        db,
        name=name,
        workspace_id=workspace_id,
        catalog=catalog,
    )
    if not readiness.ready or readiness.config is None:
        await _audit_change(
            db,
            registration=registration,
            actor_user_id=actor_user_id,
            action=connect_blocked(readiness.reason),
            event_type=AUDIT_CONNECTOR_ACCESS,
            outcome=OUTCOME_BLOCKED,
        )
        await db.commit()
        raise HTTPException(status_code=409, detail=f"MCP server is not ready: {readiness.reason}")
    runtime_id = runtime_registration_id(mcp_client_manager, registration.name)
    runtime_connected = await mcp_client_manager.is_connected(registration.name)
    if runtime_connected and runtime_id != registration.id:
        await _audit_change(
            db,
            registration=registration,
            actor_user_id=actor_user_id,
            action=connect_blocked(BLOCK_RUNTIME_NAME_CONFLICT),
            event_type=AUDIT_CONNECTOR_ACCESS,
            outcome=OUTCOME_BLOCKED,
        )
        await db.commit()
        raise HTTPException(status_code=409, detail="MCP runtime name is occupied by another ownership scope")
    if runtime_connected:
        tools = mcp_client_manager.get_tools(registration.name)
        return {"name": registration.name, "connected": True, "tool_count": len(tools), **readiness.public()}
    if runtime_id != registration.id:
        mcp_client_manager.unregister_server(registration.name)
    mcp_client_manager.register_server(readiness.config)
    connected = await mcp_client_manager.connect(registration.name)
    await _audit_change(
        db,
        registration=registration,
        actor_user_id=actor_user_id,
        action=ACTION_CONNECTED if connected else ACTION_CONNECTION_FAILED,
        event_type=AUDIT_CONNECTOR_ACCESS,
        outcome=OUTCOME_ALLOWED if connected else OUTCOME_BLOCKED,
    )
    await db.commit()
    if not connected:
        mcp_client_manager.unregister_server(registration.name)
        raise HTTPException(status_code=502, detail=f"Failed to connect to MCP server '{registration.name}'")
    tools = mcp_client_manager.get_tools(registration.name)
    return {"name": registration.name, "connected": True, "tool_count": len(tools), **readiness.public()}


async def disconnect_mcp_server(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    actor_user_id: str | None,
    mcp_client_manager: Any,
) -> dict[str, Any]:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    owns_runtime = runtime_registration_id(mcp_client_manager, registration.name) == registration.id
    disconnected = await mcp_client_manager.disconnect(registration.name) if owns_runtime else False
    if owns_runtime:
        mcp_client_manager.unregister_server(registration.name)
    await _audit_change(
        db,
        registration=registration,
        actor_user_id=actor_user_id,
        action=ACTION_DISCONNECTED,
        event_type=AUDIT_CONNECTOR_ACCESS,
    )
    await db.commit()
    return {"name": registration.name, "connected": False, "disconnected": disconnected}


async def delete_mcp_server(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    actor_user_id: str | None,
    mcp_client_manager: Any,
) -> dict[str, Any]:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    owns_runtime = runtime_registration_id(mcp_client_manager, registration.name) == registration.id
    if owns_runtime and await mcp_client_manager.is_connected(registration.name):
        await mcp_client_manager.disconnect(registration.name)
    if owns_runtime:
        mcp_client_manager.unregister_server(registration.name)
    await _audit_change(db, registration=registration, actor_user_id=actor_user_id, action=ACTION_DELETED)
    await db.delete(registration)
    await db.commit()
    return {"name": registration.name, "deleted": True}


async def list_mcp_server_tools(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    mcp_client_manager: Any,
) -> list[dict[str, Any]]:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    if not await registration_is_connected(registration, mcp_client_manager=mcp_client_manager):
        raise HTTPException(status_code=409, detail=f"MCP server '{registration.name}' is not connected")
    tools = mcp_client_manager.get_tools(registration.name)
    return [{"name": tool.name, "description": tool.description, "server_name": tool.server_name} for tool in tools]


async def mcp_server_is_connected(
    db: AsyncSession,
    *,
    name: str,
    workspace_id: str,
    mcp_client_manager: Any,
) -> bool:
    registration = await get_scoped_registration(db, name=name, workspace_id=workspace_id)
    return await registration_is_connected(registration, mcp_client_manager=mcp_client_manager)
