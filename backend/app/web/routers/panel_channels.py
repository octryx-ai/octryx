"""Auto-extracted router module: panel_channels."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._runtime import ChannelCreateRequest, ChannelUpdateRequest
from app.services.admin.connector._admin_channel_instances import create_channel as admin_create_channel
from app.services.admin.connector._admin_channel_instances import delete_channel as admin_delete_channel
from app.services.admin.connector._admin_channel_instances import get_channel_details as admin_get_channel_details
from app.services.admin.connector._admin_channel_instances import (
    list_available_channels as admin_list_available_channels,
)
from app.services.admin.connector._admin_channel_instances import (
    list_configured_channels as admin_list_configured_channels,
)
from app.services.admin.connector._admin_channel_instances import reload_channel as admin_reload_channel
from app.services.admin.connector._admin_channel_instances import update_channel as admin_update_channel
from app.services.admin.connector._admin_channel_sessions import list_call_sessions as admin_list_call_sessions
from app.services.admin.connector._admin_channel_sessions import list_channel_sessions as admin_list_channel_sessions
from app.services.admin.connector.admin_channel_service import (
    create_channel_delivery_target as admin_create_channel_delivery_target,
)
from app.services.admin.connector.admin_channel_service import (
    delete_channel_delivery_target as admin_delete_channel_delivery_target,
)
from app.services.admin.connector.admin_channel_service import (
    list_channel_delivery_logs as admin_list_channel_delivery_logs,
)
from app.services.admin.connector.admin_channel_service import (
    list_channel_delivery_targets as admin_list_channel_delivery_targets,
)
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace
from .panel_mcp_servers import router as panel_mcp_servers_router

router = APIRouter()


@router.get("/chat/api/panel/channels")
async def panel_list_channels(request: Request, db: AsyncSession = Depends(get_db)):
    """Return only channels that have been explicitly configured (DB rows)."""
    await _require_admin_api(request, db)
    from ...plugins import plugin_manager

    return JSONResponse(await admin_list_configured_channels(db, request=request, plugin_manager=plugin_manager))


@router.get("/chat/api/panel/channels/available")
async def panel_list_available_channels(request: Request, db: AsyncSession = Depends(get_db)):
    """Return channel templates that can be instantiated multiple times."""
    await _require_admin_api(request, db)
    from ...plugins import plugin_manager

    return JSONResponse(await admin_list_available_channels(request=request, plugin_manager=plugin_manager))


@router.get("/chat/api/panel/channel-sessions")
async def panel_list_channel_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_channel_sessions(db, limit=limit))


@router.get("/chat/api/panel/call-sessions")
async def panel_list_call_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_call_sessions(db, limit=limit))


@router.get("/chat/api/panel/channel-delivery-targets")
async def panel_list_channel_delivery_targets(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_channel_delivery_targets(db))


@router.get("/chat/api/panel/channel-delivery-log")
async def panel_list_channel_delivery_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    status: str | None = None,
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_channel_delivery_logs(db, limit=limit, status_filter=status))


@router.post("/chat/api/panel/channel-delivery-targets")
async def panel_create_channel_delivery_target(
    payload: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await admin_create_channel_delivery_target(db, body=payload, admin_id=admin.id))


@router.delete("/chat/api/panel/channel-delivery-targets/{target_id}")
async def panel_delete_channel_delivery_target(
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_channel_delivery_target(db, target_id=target_id, admin_id=admin.id))


@router.get("/chat/api/panel/channels/{channel_id}")
async def panel_get_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from ...plugins import plugin_manager

    return JSONResponse(
        await admin_get_channel_details(db, request=request, channel_id=channel_id, plugin_manager=plugin_manager)
    )


async def _refuse_private_channel(db: AsyncSession, project_id: object) -> JSONResponse | None:
    """A channel never runs turns in a private Workspace (its sender mappings could act as the
    owner); channels belong to shared Workspaces."""
    from ...services.project.private_workspace import private_project  # noqa: PLC0415

    if isinstance(project_id, str) and project_id and await private_project(db, project_id) is not None:
        return JSONResponse({"detail": "Channels are not available in a private Workspace.",
                             "reason": "private_workspace_has_no_channels"}, status_code=409)
    return None


@router.post("/chat/api/panel/channels")
async def panel_create_channel(
    payload: ChannelCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    if (refused := await _refuse_private_channel(db, payload.model_dump().get("project_id"))) is not None:
        return refused
    from ...plugins import plugin_manager

    return JSONResponse(
        await admin_create_channel(
            db,
            request=request,
            body=payload.model_dump(),
            admin_id=admin.id,
            plugin_manager=plugin_manager,
        )
    )


@router.put("/chat/api/panel/channels/{channel_id}")
async def panel_update_channel(
    channel_id: int,
    payload: ChannelUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    if (refused := await _refuse_private_channel(db, payload.model_dump().get("project_id"))) is not None:
        return refused
    from ...plugins import plugin_manager

    return JSONResponse(
        await admin_update_channel(
            db,
            request=request,
            channel_id=channel_id,
            body=payload.model_dump(exclude_none=True),
            admin_id=admin.id,
            plugin_manager=plugin_manager,
        )
    )


@router.delete("/chat/api/panel/channels/{channel_id}")
async def panel_delete_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    from ...plugins import plugin_manager

    return JSONResponse(
        await admin_delete_channel(db, channel_id=channel_id, admin_id=admin.id, plugin_manager=plugin_manager)
    )


@router.post("/chat/api/panel/channels/{channel_id}/reload")
async def panel_reload_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    from ...plugins import plugin_manager

    return JSONResponse(
        await admin_reload_channel(db, channel_id=channel_id, admin_id=admin.id, plugin_manager=plugin_manager)
    )


router.include_router(panel_mcp_servers_router)
