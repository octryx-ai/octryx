"""Read projections for the Workspace-scoped MCP server registry."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import McpServerRegistration, Project
from ..models.runtime.mcp_server import MCP_OWNER_PLATFORM
from .mcp_server_registry_config import registration_is_connected


async def _require_workspace(db: AsyncSession, workspace_id: str) -> None:
    workspace = await db.get(Project, str(workspace_id or "").strip())
    if workspace is None or not workspace.is_active:
        raise HTTPException(status_code=404, detail="Workspace not found")


def _serialize_registration(
    registration: McpServerRegistration,
    *,
    connected: bool,
    tool_count: int,
) -> dict[str, Any]:
    return {
        "id": registration.id,
        "name": registration.name,
        "owner_scope": registration.owner_scope,
        "workspace_id": registration.workspace_id,
        "transport": registration.transport,
        "url": registration.url,
        "description": registration.description,
        "catalog_slug": registration.catalog_slug,
        "settings": dict(registration.settings_json or {}),
        "secret_fields": sorted(binding.field_name for binding in registration.secret_bindings),
        "credential_binding_count": len(registration.secret_bindings),
        "auto_start": bool(registration.auto_start),
        "is_active": bool(registration.is_active),
        "revision": registration.revision,
        "connected": connected,
        "tool_count": tool_count,
    }


async def list_mcp_servers(
    db: AsyncSession,
    *,
    workspace_id: str,
    mcp_client_manager: Any,
) -> list[dict[str, Any]]:
    await _require_workspace(db, workspace_id)
    rows = (
        (
            await db.execute(
                select(McpServerRegistration)
                .options(selectinload(McpServerRegistration.secret_bindings))
                .where(
                    or_(
                        McpServerRegistration.owner_scope == MCP_OWNER_PLATFORM,
                        McpServerRegistration.workspace_id == workspace_id,
                    )
                )
                .order_by(
                    case((McpServerRegistration.workspace_id == workspace_id, 0), else_=1),
                    McpServerRegistration.name.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    result: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in rows:
        if row.canonical_name in seen_names:
            continue
        seen_names.add(row.canonical_name)
        connected = await registration_is_connected(row, mcp_client_manager=mcp_client_manager)
        tools = mcp_client_manager.get_tools(row.name) if connected else []
        result.append(_serialize_registration(row, connected=connected, tool_count=len(tools)))
    return result


async def list_scoped_registration_names(db: AsyncSession, *, workspace_id: str) -> list[str]:
    await _require_workspace(db, workspace_id)
    rows = list(
        (
            await db.execute(
                select(McpServerRegistration)
                .where(
                    or_(
                        McpServerRegistration.owner_scope == MCP_OWNER_PLATFORM,
                        McpServerRegistration.workspace_id == workspace_id,
                    )
                )
                .order_by(
                    case((McpServerRegistration.workspace_id == workspace_id, 0), else_=1),
                    McpServerRegistration.name.asc(),
                )
            )
        ).scalars()
    )
    names_by_identity: dict[str, str] = {}
    for row in rows:
        names_by_identity.setdefault(row.canonical_name, row.name)
    return list(names_by_identity.values())


async def serialize_mcp_server(
    registration: McpServerRegistration,
    *,
    mcp_client_manager: Any,
) -> dict[str, Any]:
    connected = await registration_is_connected(registration, mcp_client_manager=mcp_client_manager)
    tools = mcp_client_manager.get_tools(registration.name) if connected else []
    return _serialize_registration(registration, connected=connected, tool_count=len(tools))


async def list_mcp_catalog(
    db: AsyncSession,
    *,
    workspace_id: str,
    catalog: dict[str, dict[str, Any]],
    mcp_client_manager: Any,
) -> list[dict[str, Any]]:
    installed_by_slug: dict[str, list[str]] = {}
    for server in await list_mcp_servers(db, workspace_id=workspace_id, mcp_client_manager=mcp_client_manager):
        slug = str(server.get("catalog_slug") or "")
        if slug:
            installed_by_slug.setdefault(slug, []).append(str(server["name"]))
    return [
        {
            "slug": preset["slug"],
            "name": preset["name"],
            "vendor": preset.get("vendor"),
            "description": preset.get("description"),
            "source_url": preset.get("source_url"),
            "transport": preset.get("transport"),
            "default_name": preset.get("default_name"),
            "fields": preset.get("fields") or [],
            "installed_names": installed_by_slug.get(preset["slug"], []),
            "installed_count": len(installed_by_slug.get(preset["slug"], [])),
        }
        for preset in catalog.values()
    ]
