"""Admin panel routes for scenarios.

Included by ``panel_connectors.router``.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._agents import ScenarioProfileCreateRequest, ScenarioProfileUpdateRequest

from ...db import get_db
from ...services.access_control import require_existing_workspace
from ...services.admin.connector import admin_scenario_service
from .._helpers.api_guards import _require_admin_api
from .._helpers.panel_serializers import _serialize_scenario_profile

router = APIRouter()


@router.get("/chat/api/panel/scenarios")
async def panel_list_scenarios(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_scenario_service.list_scenarios(
            db,
            user_id=user.id,
            serialize_profile=_serialize_scenario_profile,
        )
    )


@router.post("/chat/api/panel/scenarios")
async def panel_create_scenario(
    payload: ScenarioProfileCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_scenario_service.create_scenario(
            db,
            user_id=user.id,
            payload=payload.model_dump(),
            serialize_profile=_serialize_scenario_profile,
        )
    )


@router.put("/chat/api/panel/scenarios/{scenario_id}")
async def panel_update_scenario(
    scenario_id: str,
    payload: ScenarioProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_scenario_service.update_scenario(
            db,
            user_id=user.id,
            scenario_id=scenario_id,
            payload=payload.model_dump(exclude_none=True),
            serialize_profile=_serialize_scenario_profile,
        )
    )


@router.delete("/chat/api/panel/scenarios/{scenario_id}")
async def panel_delete_scenario(scenario_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_scenario_service.delete_scenario(db, user_id=user.id, scenario_id=scenario_id))
