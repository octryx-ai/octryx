"""Admin panel routes for runtime settings and runtime workspace cleanup."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_runtime_panel import RuntimeSettingsUpdateRequest
from app.services.access_control import require_existing_workspace
from app.services.admin.provider.admin_runtime_service import (
    get_runtime_settings as admin_get_runtime_settings,
)
from app.services.admin.provider.admin_runtime_service import (
    update_runtime_settings as admin_update_runtime_settings,
)
from app.services.control_plane_service import (
    get_or_create_control_plane_config,
)
from app.services.session.workspace import cleanup_expired_session_workspaces
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/runtime-settings")
async def panel_get_runtime_settings(
    request: Request,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_get_runtime_settings(
            db,
            get_or_create_control_plane_config_func=get_or_create_control_plane_config,
            project_id=project_id,
        )
    )


@router.put("/chat/api/panel/runtime-settings")
async def panel_update_runtime_settings(
    payload: RuntimeSettingsUpdateRequest,
    request: Request,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, project_id)
    return JSONResponse(
        await admin_update_runtime_settings(
            db,
            payload=payload.to_update_payload(),
            get_or_create_control_plane_config_func=get_or_create_control_plane_config,
            project_id=project_id,
            actor_user_id=admin.id,
        )
    )


@router.post("/chat/api/panel/runtime-workspace/cleanup")
async def panel_cleanup_runtime_workspaces(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await cleanup_expired_session_workspaces(db))
