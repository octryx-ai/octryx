"""Admin panel routes for a Workspace's composition: view, diagnostics, binding, policy and assignment controls.

Included by ``panel_projects_c.router``.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._projects import (
    WorkspaceAssignmentControlsUpdateRequest,
    WorkspaceCompositionBindingUpdateRequest,
    WorkspacePolicyUpdateRequest,
)
from app.services.workspace_composition.admin_api import (
    get_workspace_composition_diagnostics as admin_get_workspace_composition_diagnostics,
)
from app.services.workspace_composition.admin_api import (
    get_workspace_composition_payload as admin_get_workspace_composition_payload,
)
from app.services.workspace_composition.admin_api import (
    update_workspace_assignment_controls as admin_update_workspace_assignment_controls,
)
from app.services.workspace_composition.admin_api import update_workspace_binding as admin_update_workspace_binding
from app.services.workspace_composition.admin_api import update_workspace_policy as admin_update_workspace_policy
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/projects/{project_id}/workspace-composition")
async def panel_get_workspace_composition(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_workspace_composition_payload(db, workspace_id=project_id))


@router.get("/chat/api/panel/projects/{project_id}/workspace-composition/diagnostics")
async def panel_get_workspace_composition_diagnostics(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_workspace_composition_diagnostics(db, workspace_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/workspace-composition/bindings/{binding_id}")
async def panel_update_workspace_binding(
    project_id: str,
    binding_id: str,
    payload: WorkspaceCompositionBindingUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_workspace_binding(
            db,
            workspace_id=project_id,
            binding_id=binding_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.put("/chat/api/panel/projects/{project_id}/workspace-composition/policy")
async def panel_update_workspace_policy(
    project_id: str,
    payload: WorkspacePolicyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_workspace_policy(
            db,
            workspace_id=project_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.put("/chat/api/panel/projects/{project_id}/workspace-composition/assignment-controls")
async def panel_update_workspace_assignment_controls(
    project_id: str,
    payload: WorkspaceAssignmentControlsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_workspace_assignment_controls(
            db,
            workspace_id=project_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )
