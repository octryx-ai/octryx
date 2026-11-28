"""Admin panel routes for runtimes, context budget profiles and tool result compressors."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._runtime import RuntimeCreateRequest, RuntimeUpdateRequest
from app.schemas.admin.admin_runtime_panel import (
    RuntimeDirectionRequest,
)
from app.services.admin.provider.admin_runtime_service import (
    add_runtime as admin_add_runtime,
)
from app.services.admin.provider.admin_runtime_service import (
    delete_runtime as admin_delete_runtime,
)
from app.services.admin.provider.admin_runtime_service import (
    list_runtimes as admin_list_runtimes,
)
from app.services.admin.provider.admin_runtime_service import (
    move_runtime as admin_move_runtime,
)
from app.services.admin.provider.admin_runtime_service import (
    toggle_runtime as admin_toggle_runtime,
)
from app.services.admin.provider.admin_runtime_service import (
    update_runtime as admin_update_runtime,
)
from app.services.control_plane_service import (
    delete_runtime_target,
    get_runtime_targets,
    move_runtime_target,
    toggle_runtime_target,
    upsert_runtime_target,
)
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.panel_serializers import _serialize_runtime_target

router = APIRouter()


@router.get("/chat/api/panel/runtimes")
async def panel_list_runtimes(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_list_runtimes(
            db,
            get_runtime_targets_func=get_runtime_targets,
            serialize_runtime_target=_serialize_runtime_target,
        )
    )


@router.post("/chat/api/panel/runtimes")
async def panel_add_runtime(
    payload: RuntimeCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_add_runtime(
            db,
            payload=payload.model_dump(exclude_none=True),
            upsert_runtime_target_func=upsert_runtime_target,
            serialize_runtime_target=_serialize_runtime_target,
            actor_user_id=admin.id,
        )
    )


@router.post("/chat/api/panel/runtimes/{target_id}/move")
async def panel_move_runtime(
    target_id: str,
    payload: RuntimeDirectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_move_runtime(
            db,
            target_id=target_id,
            direction=payload.direction,
            move_runtime_target_func=move_runtime_target,
            get_runtime_targets_func=get_runtime_targets,
            serialize_runtime_target=_serialize_runtime_target,
            actor_user_id=admin.id,
        )
    )


@router.post("/chat/api/panel/runtimes/{target_id}/toggle")
async def panel_toggle_runtime(
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_toggle_runtime(
            db,
            target_id=target_id,
            toggle_runtime_target_func=toggle_runtime_target,
            serialize_runtime_target=_serialize_runtime_target,
            actor_user_id=admin.id,
        )
    )


@router.put("/chat/api/panel/runtimes/{target_id}")
async def panel_update_runtime(
    target_id: str,
    payload: RuntimeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_runtime(
            db,
            target_id=target_id,
            payload=payload.model_dump(exclude_none=True),
            serialize_runtime_target=_serialize_runtime_target,
            actor_user_id=admin.id,
        )
    )


@router.delete("/chat/api/panel/runtimes/{target_id}")
async def panel_delete_runtime(
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_delete_runtime(
            db,
            target_id=target_id,
            delete_runtime_target_func=delete_runtime_target,
            actor_user_id=admin.id,
        )
    )
