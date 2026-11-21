"""Admin panel routes for a Workspace's design artifacts, readiness and trace links."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._research import (
    DesignTraceLinkCreateRequest,
    DesignTraceSyncWorkflowListUpdateRequest,
)
from app.services.admin.project.admin_project_quality_design import (
    create_project_design_trace_link as admin_create_project_design_trace_link,
)
from app.services.admin.project.admin_project_quality_design import (
    get_project_design_readiness_summary as admin_get_project_design_readiness_summary,
)
from app.services.admin.project.admin_project_quality_design import (
    get_project_design_traceability_summary as admin_get_project_design_traceability_summary,
)
from app.services.admin.project.admin_project_quality_design import (
    list_project_design_artifacts as admin_list_project_design_artifacts,
)
from app.services.admin.project.admin_project_quality_design import (
    list_project_design_trace_links as admin_list_project_design_trace_links,
)
from app.services.admin.project.admin_project_quality_design import (
    list_project_design_trace_sync_workflows as admin_list_project_design_trace_sync_workflows,
)
from app.services.admin.project.admin_project_quality_design import (
    update_project_design_trace_sync_workflows_config as admin_update_project_design_trace_sync_workflows_config,
)
from app.web._helpers.api_guards import _require_admin_api

from .panel_project_design_sync import router as panel_project_design_sync_router

router = APIRouter()


@router.get("/chat/api/panel/projects/{project_id}/design-artifacts")
async def panel_list_project_design_artifacts(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_project_design_artifacts(db, project_id=project_id))


@router.get("/chat/api/panel/projects/{project_id}/design-readiness")
async def panel_get_project_design_readiness(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_project_design_readiness_summary(db, project_id=project_id))


@router.get("/chat/api/panel/projects/{project_id}/design-traceability")
async def panel_get_project_design_traceability(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_project_design_traceability_summary(db, project_id=project_id))


@router.get("/chat/api/panel/projects/{project_id}/design-trace-sync-workflows")
async def panel_list_project_design_trace_sync_workflows(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_project_design_trace_sync_workflows(db, project_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/design-trace-sync-workflows")
async def panel_update_project_design_trace_sync_workflows(
    project_id: str,
    payload: DesignTraceSyncWorkflowListUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_design_trace_sync_workflows_config(
            db,
            project_id=project_id,
            workflows=[item.model_dump(exclude_none=True) for item in payload.workflows],
        )
    )


@router.get("/chat/api/panel/projects/{project_id}/design-trace-links")
async def panel_list_project_design_trace_links(
    project_id: str,
    request: Request,
    artifact_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_project_design_trace_links(db, project_id=project_id, artifact_id=artifact_id))


@router.post("/chat/api/panel/projects/{project_id}/design-trace-links")
async def panel_create_project_design_trace_link(
    project_id: str,
    payload: DesignTraceLinkCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_create_project_design_trace_link(
            db,
            project_id=project_id,
            payload=payload.model_dump(),
            created_by_user_id=str(current_user.id),
        )
    )


router.include_router(panel_project_design_sync_router)
