"""Admin panel routes for MCP servers: catalog, configuration, connection and tool listing."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._connectors import (
    MCPCatalogInstallRequest,
    MCPServerCreateRequest,
    MCPServerUpdateRequest,
)
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.context_runtime import _MCP_CATALOG

from ...services.access_control import require_existing_workspace
from .panel_branding_voice import router as panel_branding_voice_router

router = APIRouter()


@router.get("/chat/api/panel/mcp/servers")
async def panel_mcp_list_servers(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_queries import list_mcp_servers

    return JSONResponse(
        await list_mcp_servers(db, workspace_id=workspace_id, mcp_client_manager=mcp_client_manager)
    )


@router.get("/chat/api/panel/mcp/catalog")
async def panel_mcp_catalog(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_queries import list_mcp_catalog

    return JSONResponse(
        await list_mcp_catalog(
            db,
            workspace_id=workspace_id,
            mcp_client_manager=mcp_client_manager,
            catalog=_MCP_CATALOG,
        )
    )


@router.post("/chat/api/panel/mcp/servers")
async def panel_mcp_add_server(
    payload: MCPServerCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_queries import serialize_mcp_server
    from ...services.mcp_server_registry_writes import create_remote_mcp_server

    registration = await create_remote_mcp_server(
        db,
        body=payload.model_dump(exclude_none=True),
        actor_user_id=admin.id,
    )
    return JSONResponse(await serialize_mcp_server(registration, mcp_client_manager=mcp_client_manager))


@router.post("/chat/api/panel/mcp/catalog/{slug}/install")
async def panel_mcp_install_catalog_server(
    slug: str,
    payload: MCPCatalogInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_queries import serialize_mcp_server
    from ...services.mcp_server_registry_writes import install_catalog_mcp_server

    registration = await install_catalog_mcp_server(
        db,
        slug=slug,
        body=payload.model_dump(exclude_none=True),
        catalog=_MCP_CATALOG,
        actor_user_id=admin.id,
    )
    return JSONResponse(await serialize_mcp_server(registration, mcp_client_manager=mcp_client_manager))


@router.put("/chat/api/panel/mcp/servers/{name}")
async def panel_mcp_update_server(
    name: str,
    payload: MCPServerUpdateRequest,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_queries import serialize_mcp_server
    from ...services.mcp_server_registry_writes import update_mcp_server

    registration = await update_mcp_server(
        db,
        name=name,
        workspace_id=workspace_id,
        body=payload.model_dump(exclude_none=True),
        catalog=_MCP_CATALOG,
        actor_user_id=admin.id,
        mcp_client_manager=mcp_client_manager,
    )
    return JSONResponse(await serialize_mcp_server(registration, mcp_client_manager=mcp_client_manager))


@router.get("/chat/api/panel/mcp/servers/{name}/readiness")
async def panel_mcp_server_readiness(
    name: str,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.mcp_server_registry import mcp_server_readiness

    registration, readiness = await mcp_server_readiness(
        db,
        name=name,
        workspace_id=workspace_id,
        catalog=_MCP_CATALOG,
    )
    return JSONResponse({"name": registration.name, **readiness.public()})


@router.post("/chat/api/panel/mcp/servers/{name}/connect")
async def panel_mcp_connect(
    name: str,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_connections import connect_mcp_server

    return JSONResponse(
        await connect_mcp_server(
            db,
            name=name,
            workspace_id=workspace_id,
            catalog=_MCP_CATALOG,
            actor_user_id=admin.id,
            mcp_client_manager=mcp_client_manager,
        )
    )


@router.post("/chat/api/panel/mcp/servers/{name}/disconnect")
async def panel_mcp_disconnect(
    name: str,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_connections import disconnect_mcp_server

    return JSONResponse(
        await disconnect_mcp_server(
            db,
            name=name,
            workspace_id=workspace_id,
            actor_user_id=admin.id,
            mcp_client_manager=mcp_client_manager,
        )
    )


@router.delete("/chat/api/panel/mcp/servers/{name}")
async def panel_mcp_delete_server(
    name: str,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, workspace_id)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_connections import delete_mcp_server

    return JSONResponse(
        await delete_mcp_server(
            db,
            name=name,
            workspace_id=workspace_id,
            actor_user_id=admin.id,
            mcp_client_manager=mcp_client_manager,
        )
    )


@router.get("/chat/api/panel/mcp/servers/{name}/tools")
async def panel_mcp_list_tools(
    name: str,
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...plugins.mcp.client import mcp_client_manager
    from ...services.mcp_server_registry_connections import list_mcp_server_tools

    return JSONResponse(
        await list_mcp_server_tools(
            db,
            name=name,
            workspace_id=workspace_id,
            mcp_client_manager=mcp_client_manager,
        )
    )


router.include_router(panel_branding_voice_router)
