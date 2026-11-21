"""Admin orchestration for mirroring MCP resources and prompts into a workspace."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from ....plugins.mcp.catalog_discovery import (
    discover_mcp_prompts,
    discover_mcp_resources,
    failed_discovery_kinds,
)
from ...mcp_resource_catalog import mirror_mcp_server_resources
from ...mcp_resource_identity import canonical_mcp_server_identity
from ...mcp_resource_states import STATE_AMBIGUOUS_SERVER


async def mirror_mcp_server_resources_for_workspace(
    db: AsyncSession,
    *,
    server_name: str,
    workspace_id: str,
    mcp_client_manager: Any,
    actor_user_id: str | None = None,
    auto_connect: bool = True,
) -> dict[str, Any]:
    """Mirror one connected server's resources and prompts into a workspace catalog.

    Only the discovered public resource and prompt lists are read. Server
    connection configuration is never touched, so no environment, header, or OAuth
    material can be persisted or returned, and resource URIs are redacted by the
    catalog before they are stored.

    Two preconditions are enforced here rather than inside the mirror, because
    both are facts about the *transport* the pure catalog writer must not know:

    - exactly one configured server owns the canonical (casefolded) identity the
      catalog is keyed by, so ``demo`` and ``DEMO`` cannot write into each other's
      catalog;
    - both discovery calls actually answered. A mirror run retires every entry it
      did not see, so a swallowed listing failure would disable a whole catalog
      and record a false "missing" lifecycle. A failed discovery therefore writes
      nothing at all and reports the failure.
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

    canonical_server = await _connected_canonical_server(
        db,
        server_name=normalized_server,
        workspace_id=normalized_workspace_id,
        mcp_client_manager=mcp_client_manager,
        actor_user_id=actor_user_id,
        auto_connect=auto_connect,
    )
    resources, prompts = await _discover_catalog(mcp_client_manager, canonical_server)
    result = await mirror_mcp_server_resources(
        db,
        workspace_id=normalized_workspace_id,
        server_name=canonical_server,
        resources=list(resources.items),
        prompts=list(prompts.items),
    )
    await db.commit()
    return {"workspace_id": normalized_workspace_id, **result}


async def _connected_canonical_server(
    db: AsyncSession,
    *,
    server_name: str,
    workspace_id: str,
    mcp_client_manager: Any,
    actor_user_id: str | None,
    auto_connect: bool,
) -> str:
    from ...mcp_server_registry_connections import mcp_server_is_connected

    connected = await mcp_server_is_connected(
        db,
        name=server_name,
        workspace_id=workspace_id,
        mcp_client_manager=mcp_client_manager,
    )
    if not connected and auto_connect:
        from app.web._helpers.context_runtime import _MCP_CATALOG

        from ...mcp_server_registry_connections import connect_mcp_server

        await connect_mcp_server(
            db,
            name=server_name,
            workspace_id=workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=actor_user_id,
            mcp_client_manager=mcp_client_manager,
        )
    canonical_server = _canonical_server(mcp_client_manager, server_name)
    connected = await mcp_server_is_connected(
        db,
        name=canonical_server,
        workspace_id=workspace_id,
        mcp_client_manager=mcp_client_manager,
    )
    if not connected:
        raise HTTPException(status_code=409, detail=f"MCP server '{canonical_server}' is not connected")
    return canonical_server


def _canonical_server(mcp_client_manager: Any, server_name: str) -> str:
    configured = [str(getattr(server, "name", "") or "") for server in mcp_client_manager.list_servers()]
    canonical_server, identity_state = canonical_mcp_server_identity(configured, server_name)
    if identity_state == STATE_AMBIGUOUS_SERVER:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Several configured MCP servers share the canonical identity of '{server_name}'. "
                "Rename them so one governed catalog describes one server."
            ),
        )
    if identity_state or mcp_client_manager.get_server(canonical_server) is None:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' is not registered")
    return canonical_server


async def _discover_catalog(mcp_client_manager: Any, canonical_server: str) -> tuple[Any, Any]:
    resources = await discover_mcp_resources(mcp_client_manager, canonical_server)
    prompts = await discover_mcp_prompts(mcp_client_manager, canonical_server)
    failed = failed_discovery_kinds([resources, prompts])
    if failed:
        # Nothing is written: an incomplete view of the server would retire
        # entries that still exist.
        raise HTTPException(
            status_code=502,
            detail=(
                f"MCP {'/'.join(failed)} discovery did not answer for server '{canonical_server}'; "
                "nothing was mirrored."
            ),
        )
    return resources, prompts


__all__ = ["mirror_mcp_server_resources_for_workspace"]
