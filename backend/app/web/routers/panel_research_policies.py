"""Admin research-policy API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._research import (
    ResearchPolicyProfileCreateRequest,
    ResearchPolicyProfileUpdateRequest,
    ResearchPolicyVersionCreateRequest,
    ResearchPolicyVersionUpdateRequest,
    WorkspaceResearchPolicyUpdateRequest,
)
from app.services.admin.engineering_knowledge._admin_research_policy_workspace import (
    get_workspace_research_policy,
    update_workspace_research_policy,
)
from app.web._helpers.api_guards import _require_admin_api

from ...services.admin.engineering_knowledge.admin_research_policy_service import (
    create_research_policy_profile,
    create_research_policy_version,
    delete_research_policy_profile,
    list_research_policies,
    update_research_policy_profile,
    update_research_policy_version,
)

router = APIRouter()


@router.get("/chat/api/panel/research-policies")
async def panel_list_research_policies(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await list_research_policies(db))


@router.post("/chat/api/panel/research-policies")
async def panel_create_research_policy(
    payload: ResearchPolicyProfileCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await create_research_policy_profile(
            db,
            admin_id=admin.id,
            payload=payload.model_dump(),
        )
    )


@router.put("/chat/api/panel/research-policies/{profile_id}")
async def panel_update_research_policy(
    profile_id: str,
    payload: ResearchPolicyProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await update_research_policy_profile(
            db,
            profile_id=profile_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    )


@router.delete("/chat/api/panel/research-policies/{profile_id}")
async def panel_delete_research_policy(profile_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await delete_research_policy_profile(db, profile_id=profile_id))


@router.post("/chat/api/panel/research-policies/{profile_id}/versions")
async def panel_create_research_policy_version(
    profile_id: str,
    payload: ResearchPolicyVersionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await create_research_policy_version(
            db,
            admin_id=admin.id,
            profile_id=profile_id,
            payload=payload.model_dump(),
        )
    )


@router.put("/chat/api/panel/research-policies/{profile_id}/versions/{version_id}")
async def panel_update_research_policy_version(
    profile_id: str,
    version_id: str,
    payload: ResearchPolicyVersionUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await update_research_policy_version(
            db,
            admin_id=admin.id,
            profile_id=profile_id,
            version_id=version_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    )


@router.get("/chat/api/panel/projects/{project_id}/research-policy")
async def panel_get_workspace_research_policy(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_workspace_research_policy(db, workspace_id=project_id))


@router.put("/chat/api/panel/projects/{project_id}/research-policy")
async def panel_update_workspace_research_policy(
    project_id: str,
    payload: WorkspaceResearchPolicyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await update_workspace_research_policy(
            db,
            workspace_id=project_id,
            admin_id=admin.id,
            payload=payload.model_dump(exclude_none=True),
        )
    )
