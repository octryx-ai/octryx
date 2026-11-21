"""Auto-extracted router module: panel_tasks."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_sla_panel import SLADefinitionCreateRequest, SLADefinitionUpdateRequest
from app.services.admin.task._admin_task_management import list_tasks as admin_list_tasks
from app.services.admin.task._admin_task_sla import (
    create_task_sla_definition_for_admin as admin_create_task_sla_definition,
)
from app.services.admin.task._admin_task_sla import (
    delete_task_sla_definition_for_admin as admin_delete_task_sla_definition,
)
from app.services.admin.task._admin_task_sla import list_task_sla_breaches_for_admin as admin_list_task_sla_breaches
from app.services.admin.task._admin_task_sla import (
    list_task_sla_definitions_for_admin as admin_list_task_sla_definitions,
)
from app.services.admin.task._admin_task_sla import (
    update_task_sla_definition_for_admin as admin_update_task_sla_definition,
)
from app.web._helpers.api_guards import _require_admin_api

from .panel_secrets_flags import router as panel_secrets_flags_router

router = APIRouter()


@router.get("/chat/api/panel/tasks")
async def panel_list_tasks(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_tasks(db))


@router.get("/chat/api/panel/sla-definitions")
async def panel_list_sla_definitions(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_task_sla_definitions(db))


@router.post("/chat/api/panel/sla-definitions")
async def panel_create_sla_definition(
    payload: SLADefinitionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_create_task_sla_definition(db, payload=payload.model_dump()))


@router.put("/chat/api/panel/sla-definitions/{definition_id}")
async def panel_update_sla_definition(
    definition_id: str,
    payload: SLADefinitionUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_task_sla_definition(
            db,
            definition_id=definition_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/chat/api/panel/sla-definitions/{definition_id}")
async def panel_delete_sla_definition(definition_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_task_sla_definition(db, definition_id=definition_id))


@router.get("/chat/api/panel/sla-breaches")
async def panel_list_sla_breaches(
    request: Request,
    unresolved_only: bool = False,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_list_task_sla_breaches(
            db,
            unresolved_only=bool(unresolved_only),
            limit=int(limit),
        )
    )


router.include_router(panel_secrets_flags_router)
