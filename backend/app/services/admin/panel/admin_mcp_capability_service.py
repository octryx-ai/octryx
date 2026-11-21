"""Admin orchestration for mirroring MCP capabilities into a workspace catalog."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from ...mcp_capability_catalog import mirror_mcp_server_capabilities


async def mirror_mcp_server_capabilities_for_workspace(
    db: AsyncSession,
    *,
    server_name: str,
    workspace_id: str,
    mcp_client_manager: Any,
    actor_user_id: str | None = None,
    auto_connect: bool = True,
) -> dict[str, Any]:
    """Mirror one connected server's tools into the workspace capability catalog.

    Only the discovered public tool list is read. Server connection configuration
    is never touched, so no environment, header, or OAuth material can be
    persisted or returned.
    """
    normalized_server = str(server_name or "").strip()
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_server:
        raise HTTPException(status_code=400, detail="MCP server name is required")
    if not normalized_workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    workspace = (
        await db.execute(select(Project).where(Project.id == normalized_workspace_id))
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    from ...mcp_server_registry_connections import mcp_server_is_connected

    connected = await mcp_server_is_connected(
        db,
        name=normalized_server,
        workspace_id=normalized_workspace_id,
        mcp_client_manager=mcp_client_manager,
    )
    if not connected and auto_connect:
        from app.web._helpers.context_runtime import _MCP_CATALOG

        from ...mcp_server_registry_connections import connect_mcp_server

        await connect_mcp_server(
            db,
            name=normalized_server,
            workspace_id=normalized_workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=actor_user_id,
            mcp_client_manager=mcp_client_manager,
        )
        connected = True
    if not connected:
        raise HTTPException(status_code=409, detail=f"MCP server '{normalized_server}' is not connected")

    result = await mirror_mcp_server_capabilities(
        db,
        workspace_id=normalized_workspace_id,
        server_name=normalized_server,
        tools=mcp_client_manager.get_tools(normalized_server),
    )
    await db.commit()
    return {"workspace_id": normalized_workspace_id, **result}


__all__ = ["mirror_mcp_server_capabilities_for_workspace"]
