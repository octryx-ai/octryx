"""Auto-extracted router module: panel_projects_c."""

from functools import partial

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._projects import (
    ProjectResourceAssignmentsUpdateRequest,
    ProjectSkillAssignmentsUpdateRequest,
)
from app.services.admin.project.admin_project_resource_service import (
    get_project_resource_assignments as admin_get_project_resource_assignments,
)
from app.services.admin.project.admin_project_resource_service import (
    update_project_resource_assignments as admin_update_project_resource_assignments,
)
from app.services.skill_assignment_service import get_project_skill_assignments as admin_get_project_skill_assignments
from app.services.skill_assignment_service import (
    update_project_skill_assignments as admin_update_project_skill_assignments,
)
from app.web._helpers.api_guards import _require_admin_api

from ...services.admin.project.admin_project_config_service import (
    get_project_config_payload,
    merge_project_config,
)
from ...services.admin.project.admin_project_connector_access_service import (
    connector_limits_in_workspaces,
    list_project_connector_access,
    update_project_connector_access,
)
from ...services.admin.project.workspace_connection_service import (
    get_workspace_connection,
    save_workspace_connection,
    test_workspace_connection,
)
from ...services.connector_test_service import run_connector_connection_test
from .panel_workspace_composition import router as panel_workspace_composition_router

router = APIRouter()

# ──────────────────────────────────────────────────────────
# Project config (TTS/STT overrides)
# ──────────────────────────────────────────────────────────

@router.get("/chat/api/panel/projects/{project_id}/config")
async def panel_get_project_config(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return the full config dict for a project."""
    await _require_admin_api(request, db)
    return JSONResponse(await get_project_config_payload(db, project_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/config")
async def panel_update_project_config(
    project_id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Merge TTS/STT settings into project.config (partial update)."""
    current_user = await _require_admin_api(request, db)
    return JSONResponse(
        await merge_project_config(
            db,
            project_id=project_id,
            patch=payload,
            actor_user_id=current_user.id,
        )
    )


@router.get("/chat/api/panel/projects/{project_id}/connectors")
async def panel_get_project_connector_access(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await list_project_connector_access(db, project_id=project_id))


@router.get("/chat/api/panel/connectors/{connector_name}/workspace-limits")
async def panel_get_connector_limits_in_workspaces(
    connector_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """One connector's limits in the Workspaces named by ``ids`` (repeated): one request, not one per Workspace."""
    user = await _require_admin_api(request, db)
    return JSONResponse(await connector_limits_in_workspaces(
        db, connector_name=connector_name, project_ids=request.query_params.getlist("ids")[:200], user_id=user.id))


@router.put("/chat/api/panel/projects/{project_id}/connectors/{connector_name}")
async def panel_update_project_connector_access(
    project_id: str,
    connector_name: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await update_project_connector_access(
            db,
            project_id=project_id,
            connector_name=connector_name,
            payload=payload,
        )
    )


# The Workspace's own Confluence/Jira connection (use global, or an own credential unit).
@router.get("/chat/api/panel/projects/{project_id}/connectors/{connector_name}/connection")
async def panel_get_workspace_connection(
    project_id: str, connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_workspace_connection(db, project_id=project_id, connector=connector_name))


@router.put("/chat/api/panel/projects/{project_id}/connectors/{connector_name}/connection")
async def panel_save_workspace_connection(
    project_id: str, connector_name: str, payload: dict, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await save_workspace_connection(
            db, project_id=project_id, connector=connector_name, payload=payload, actor_id=user.id
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/connectors/{connector_name}/connection/test")
async def panel_test_workspace_connection(
    project_id: str, connector_name: str, request: Request, db: AsyncSession = Depends(get_db)
):
    user = await _require_admin_api(request, db)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    return JSONResponse(
        await test_workspace_connection(
            db,
            project_id=project_id,
            connector=connector_name,
            payload=payload,
            run_connection_test=partial(run_connector_connection_test, db=db, scope_check=True),
            actor_id=user.id,
        )
    )


@router.get("/chat/api/panel/projects/{project_id}/resources")
async def panel_get_project_resource_assignments(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_project_resource_assignments(db, project_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/resources")
async def panel_update_project_resource_assignments(
    project_id: str,
    payload: ProjectResourceAssignmentsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_resource_assignments(
            db,
            project_id=project_id,
            payload=payload.model_dump(exclude_unset=True),
            actor_user_id=current_user.id,
        )
    )


@router.get("/chat/api/panel/projects/{project_id}/skills")
async def panel_get_project_skill_assignments(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_project_skill_assignments(db, project_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/skills")
async def panel_update_project_skill_assignments(
    project_id: str,
    payload: ProjectSkillAssignmentsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_skill_assignments(
            db,
            project_id=project_id,
            payload=payload.model_dump(exclude_unset=True, exclude_none=True),
        )
    )


router.include_router(panel_workspace_composition_router)
