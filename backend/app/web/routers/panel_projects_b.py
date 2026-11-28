"""Auto-extracted router module: panel_projects_b."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._projects import ProjectRuntimePolicyUpdateRequest
from app.schemas.admin.admin_panel._repositories import (
    CodeRepositoryIndexRequest,
    CodeRepositoryRequest,
    CodeRepositoryUpdateRequest,
)
from app.schemas.admin.admin_panel._research import (
    DesignArtifactBootstrapRequest,
    DesignArtifactCreateRequest,
    DesignArtifactUpdateRequest,
)
from app.services.admin.project.admin_project_quality_config import (
    update_project_runtime_policy as admin_update_project_runtime_policy,
)
from app.services.admin.project.admin_project_quality_design import (
    bootstrap_project_design_artifacts as admin_bootstrap_project_design_artifacts,
)
from app.services.admin.project.admin_project_quality_design import (
    create_project_design_artifact as admin_create_project_design_artifact,
)
from app.services.admin.project.admin_project_quality_design import (
    delete_project_design_artifact as admin_delete_project_design_artifact,
)
from app.services.admin.project.admin_project_quality_design import (
    update_project_design_artifact as admin_update_project_design_artifact,
)
from app.services.code_intelligence.graph_admin import (
    get_code_graph_admin_status as admin_get_code_graph_admin_status,
)
from app.services.code_intelligence.indexing import (
    run_code_index as admin_run_code_index,
)
from app.services.code_intelligence.repository import (
    create_code_repository as admin_create_code_repository,
)
from app.services.code_intelligence.repository import (
    delete_code_repository as admin_delete_code_repository,
)
from app.services.code_intelligence.repository import (
    list_code_repositories as admin_list_code_repositories,
)
from app.services.code_intelligence.repository import (
    update_code_repository as admin_update_code_repository,
)
from app.services.code_intelligence.storage_capabilities import detect_code_intelligence_capabilities
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace

router = APIRouter()


@router.post("/chat/api/panel/projects/{project_id}/design-artifacts/bootstrap")
async def panel_bootstrap_project_design_artifacts(
    project_id: str,
    payload: DesignArtifactBootstrapRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_bootstrap_project_design_artifacts(
            db,
            project_id=project_id,
            include_optional=payload.include_optional,
        )
    )


@router.post("/chat/api/panel/projects/{project_id}/design-artifacts")
async def panel_create_project_design_artifact(
    project_id: str,
    payload: DesignArtifactCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_create_project_design_artifact(
            db,
            project_id=project_id,
            payload=payload.model_dump(),
        )
    )


@router.put("/chat/api/panel/projects/{project_id}/design-artifacts/{artifact_id}")
async def panel_update_project_design_artifact(
    project_id: str,
    artifact_id: str,
    payload: DesignArtifactUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_design_artifact(
            db,
            artifact_id=artifact_id,
            payload={"project_id": project_id, **payload.model_dump(exclude_unset=True)},
        )
    )


@router.delete("/chat/api/panel/projects/{project_id}/design-artifacts/{artifact_id}")
async def panel_delete_project_design_artifact(
    project_id: str,
    artifact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_project_design_artifact(db, artifact_id=artifact_id))


@router.get("/chat/api/panel/code-repositories")
async def panel_list_code_repositories(
    request: Request,
    project_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        {
            "items": await admin_list_code_repositories(db, project_id=project_id),
            "capabilities": detect_code_intelligence_capabilities(),
        }
    )


@router.post("/chat/api/panel/code-repositories")
async def panel_create_code_repository(
    request: Request,
    payload: CodeRepositoryRequest,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(await admin_create_code_repository(db, payload.model_dump()))


@router.put("/chat/api/panel/code-repositories/{repository_id}")
async def panel_update_code_repository(
    repository_id: str,
    request: Request,
    payload: CodeRepositoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    await require_existing_workspace(db, admin.id, payload.project_id)
    return JSONResponse(await admin_update_code_repository(db, repository_id, payload.model_dump(exclude_unset=True)))


@router.delete("/chat/api/panel/code-repositories/{repository_id}")
async def panel_delete_code_repository(
    repository_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    await admin_delete_code_repository(db, repository_id)
    return JSONResponse({"deleted": True, "repository_id": repository_id})


@router.get("/chat/api/panel/code-repositories/{repository_id}/code-graph")
async def panel_get_code_repository_graph_status(
    repository_id: str,
    request: Request,
    project_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_get_code_graph_admin_status(db, repository_id=repository_id, project_id=project_id)
    )


@router.post("/chat/api/panel/code-repositories/{repository_id}/index")
async def panel_run_code_repository_index(
    repository_id: str,
    request: Request,
    payload: CodeRepositoryIndexRequest,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    result = await admin_run_code_index(db, repository_id=repository_id, force=payload.force, trigger="admin_panel")
    result["repository"]["code_graph_status"] = await admin_get_code_graph_admin_status(
        db, repository_id=repository_id
    )
    return JSONResponse(result)


@router.put("/chat/api/panel/projects/{project_id}/runtime-policy")
async def panel_update_project_runtime_policy(
    project_id: str,
    payload: ProjectRuntimePolicyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_project_runtime_policy(
            db,
            project_id=project_id,
            runtime_policy=payload.runtime_policy,
        )
    )
