"""The Corporate Identity a Workspace uses and the profile's Spec Studio locks (admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.corp_identity.workspace import (
    LOCKABLE,
    WORKSPACE_KEY,
    CorporateIdentityError,
    effective_profile,
    normalize_workspace_profile_id,
    require_profile,
    set_studio_locks,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


def _refusal(error: CorporateIdentityError) -> HTTPException:
    status = 404 if error.code == "corp_identity_profile_unknown" else 400
    return HTTPException(status_code=status, detail={"errors": [{"code": error.code, "message": str(error)}]})


async def _view(db: AsyncSession, project_id: str) -> dict:
    from app.models import Project

    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    config = project.config if isinstance(project.config, dict) else {}
    return {"chosen": str(config.get(WORKSPACE_KEY) or ""), "effective": await effective_profile(db, project_id),
            "lockable": sorted(LOCKABLE)}


@router.get("/chat/api/panel/workspaces/{project_id}/corp-identity")
async def panel_workspace_corp_identity(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await _view(db, project_id))


@router.put("/chat/api/panel/workspaces/{project_id}/corp-identity")
async def panel_set_workspace_corp_identity(project_id: str, payload: dict, request: Request,
                                            db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    from app.services.admin.project.admin_project_config_service import merge_project_config

    try:
        profile_id = normalize_workspace_profile_id(payload.get("profile_id"))
        await require_profile(db, profile_id)
    except CorporateIdentityError as error:
        raise _refusal(error) from None
    await _view(db, project_id)  # 404 for an unknown Workspace before anything is written
    await merge_project_config(db, project_id=project_id, patch={WORKSPACE_KEY: profile_id},
                               actor_user_id=user.id)
    await db.commit()
    return JSONResponse(await _view(db, project_id))


@router.put("/chat/api/panel/corp-identities/{profile_id}/studio-locks")
async def panel_set_studio_locks(profile_id: str, payload: dict, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    try:
        locks = await set_studio_locks(db, profile_id, payload.get("paths"))
    except CorporateIdentityError as error:
        raise _refusal(error) from None
    await db.commit()
    return JSONResponse({"profile_id": profile_id, "studio_locks": locks})
