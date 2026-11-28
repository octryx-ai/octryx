"""Admin transport for MCP capability, resource, and prompt mirroring."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._connectors import MCPCapabilityMirrorRequest
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace

router = APIRouter()


@router.post("/chat/api/panel/mcp/servers/{name}/mirror-capabilities")
async def panel_mcp_mirror_capabilities(
    name: str,
    payload: MCPCapabilityMirrorRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mirror one server's discovered tools into a workspace capability catalog."""
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.admin.panel.admin_mcp_capability_service import (
        mirror_mcp_server_capabilities_for_workspace,
    )

    return JSONResponse(
        await mirror_mcp_server_capabilities_for_workspace(
            db,
            server_name=name,
            workspace_id=payload.workspace_id,
            mcp_client_manager=mcp_client_manager,
            actor_user_id=admin.id,
            auto_connect=payload.auto_connect,
        )
    )


@router.post("/chat/api/panel/mcp/servers/{name}/mirror-resources")
async def panel_mcp_mirror_resources(
    name: str,
    payload: MCPCapabilityMirrorRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Mirror one server's resources and prompts into a workspace catalog."""
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.admin.panel.admin_mcp_resource_service import (
        mirror_mcp_server_resources_for_workspace,
    )

    return JSONResponse(
        await mirror_mcp_server_resources_for_workspace(
            db,
            server_name=name,
            workspace_id=payload.workspace_id,
            mcp_client_manager=mcp_client_manager,
            actor_user_id=admin.id,
            auto_connect=payload.auto_connect,
        )
    )
