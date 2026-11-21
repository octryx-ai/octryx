"""Auto-extracted router module: panel_projects_a."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._projects import (
    ProjectRepoQualityUpdateRequest,
    ProjectRepositoryBootstrapUpdateRequest,
)
from app.schemas.admin.admin_panel._users import ProjectAccessUpdateRequest
from app.services.admin.project.admin_project_access_service import (
    get_project_access as admin_get_project_access,
)
from app.services.admin.project.admin_project_access_service import (
    replace_project_access as admin_replace_project_access,
)
from app.services.admin.project.admin_project_access_service import require_administrable_project
from app.services.admin.project.admin_project_quality_config import (
    update_project_repo_quality_config as admin_update_project_repo_quality_config,
)
from app.services.admin.project.admin_project_quality_config import (
    update_project_repository_bootstrap as admin_update_project_repository_bootstrap,
)
from app.services.admin.project.admin_project_quality_overview import (
    list_projects_for_quality_config as admin_list_projects_for_quality_config,
)
from app.web._helpers.api_guards import _require_admin_api, _require_admin_permission_api

from .panel_project_design_trace import router as panel_project_design_trace_router

router = APIRouter()


@router.get("/chat/api/panel/projects")
async def panel_list_projects(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from app.services.project.default_workspace import default_workspace_id

    default_id = await default_workspace_id(db)
    from app.services.project.workspace_list_fields import workspace_list_fields

    projects = await admin_list_projects_for_quality_config(db)
    summary = await workspace_list_fields(db, (project.get("id") for project in projects))
    return JSONResponse([
        {**project, **summary.get(str(project.get("id")), {}), "is_default": project.get("id") == default_id}
        for project in projects
    ])


@router.get("/chat/api/panel/projects/{project_id}/access")
async def panel_get_project_access(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    viewer = await _require_admin_permission_api(request, db, resource="projects", action="read")
    await require_administrable_project(db, project_id, str(viewer.id))
    return JSONResponse(await admin_get_project_access(db, project_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/access")
async def panel_update_project_access(
    project_id: str,
    payload: ProjectAccessUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="projects", action="write")
    await require_administrable_project(db, project_id, str(admin.id))
    return JSONResponse(
        await admin_replace_project_access(
            db,
            project_id=project_id,
            assignments=[item.model_dump() for item in payload.assignments],
            group_assignments=[item.model_dump() for item in payload.group_assignments],
            role_assignments=[item.model_dump() for item in payload.role_assignments],
            granted_by_user_id=str(admin.id),
        )
    )


@router.put("/chat/api/panel/projects/{project_id}/repo-quality")
async def panel_update_project_repo_quality(
    project_id: str,
    payload: ProjectRepoQualityUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_repo_quality_config(
            db,
            project_id=project_id,
            repo_code_quality=payload.repo_code_quality,
        )
    )


@router.put("/chat/api/panel/projects/{project_id}/repository-bootstrap")
async def panel_update_project_repository_bootstrap(
    project_id: str,
    payload: ProjectRepositoryBootstrapUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_repository_bootstrap(
            db,
            project_id=project_id,
            repository_bootstrap=payload.repository_bootstrap,
        )
    )


router.include_router(panel_project_design_trace_router)
