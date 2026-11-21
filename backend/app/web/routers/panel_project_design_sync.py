"""Admin panel routes for syncing a Workspace's design traceability and its sync workflows."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._research import (
    DesignArtifactTaskCreateRequest,
    DesignCheckpointSyncRequest,
    DesignReleaseSyncRequest,
    DesignTraceSyncWorkflowRequest,
    DesignTraceSyncWorkflowRunRequest,
    DesignTraceSyncWorkflowTaskCreateRequest,
)
from app.services.access_control import require_existing_workspace
from app.services.admin.project.admin_project_quality_design import (
    create_project_design_trace_sync_workflow_task_instance,
)
from app.services.admin.project.admin_project_quality_design import (
    create_project_task_from_design_artifact as admin_create_project_task_from_design_artifact,
)
from app.services.admin.project.admin_project_quality_design import (
    delete_project_design_trace_link as admin_delete_project_design_trace_link,
)
from app.services.admin.project.admin_project_quality_design import (
    delete_project_design_trace_sync_template_entry as admin_delete_project_design_trace_sync_template_entry,
)
from app.services.admin.project.admin_project_quality_design import (
    run_project_design_trace_sync_workflow as admin_run_project_design_trace_sync_workflow,
)
from app.services.admin.project.admin_project_quality_design import (
    sync_project_design_checkpoints as admin_sync_project_design_checkpoints,
)
from app.services.admin.project.admin_project_quality_design import (
    sync_project_design_releases as admin_sync_project_design_releases,
)
from app.services.admin.project.admin_project_quality_design import (
    upsert_project_design_trace_sync_template_entry as admin_upsert_project_design_trace_sync_template_entry,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.post("/chat/api/panel/projects/{project_id}/design-artifacts/{artifact_id}/create-task")
async def panel_create_project_task_from_design_artifact(
    project_id: str,
    artifact_id: str,
    payload: DesignArtifactTaskCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_create_project_task_from_design_artifact(
            db,
            project_id=project_id,
            artifact_id=artifact_id,
            user_id=str(current_user.id),
            payload=payload.model_dump(),
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-traceability/sync-releases")
async def panel_sync_project_design_releases(
    project_id: str,
    payload: DesignReleaseSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_sync_project_design_releases(
            db,
            project_id=project_id,
            limit_per_repository=payload.limit_per_repository,
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-traceability/sync-checkpoints")
async def panel_sync_project_design_checkpoints(
    project_id: str,
    payload: DesignCheckpointSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_sync_project_design_checkpoints(
            db,
            project_id=project_id,
            limit_per_repository=payload.limit_per_repository,
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-trace-sync-workflows/{workflow_id}/run")
async def panel_run_project_design_trace_sync_workflow(
    project_id: str,
    workflow_id: str,
    payload: DesignTraceSyncWorkflowRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_run_project_design_trace_sync_workflow(
            db,
            project_id=project_id,
            workflow_id=workflow_id,
            limit_per_repository=payload.limit_per_repository,
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-trace-sync-workflows/{workflow_id}/create-task")
async def panel_create_project_design_trace_sync_workflow_task(
    project_id: str,
    workflow_id: str,
    payload: DesignTraceSyncWorkflowTaskCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await create_project_design_trace_sync_workflow_task_instance(
            db,
            project_id=project_id,
            workflow_id=workflow_id,
            user_id=admin.id,
            payload=payload.model_dump(),
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-trace-sync-templates")
async def panel_upsert_project_design_trace_sync_template(
    project_id: str,
    payload: DesignTraceSyncWorkflowRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_upsert_project_design_trace_sync_template_entry(
            db,
            project_id=project_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.delete("/chat/api/panel/projects/{project_id}/design-trace-sync-templates/{template_id}")
async def panel_delete_project_design_trace_sync_template(
    project_id: str,
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(
        await admin_delete_project_design_trace_sync_template_entry(
            db,
            project_id=project_id,
            template_id=template_id,
        )
    )


@router.delete("/chat/api/panel/projects/{project_id}/design-trace-links/{link_id}")
async def panel_delete_project_design_trace_link(
    project_id: str,
    link_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await require_existing_workspace(db, project_id)
    return JSONResponse(await admin_delete_project_design_trace_link(db, link_id=link_id))
