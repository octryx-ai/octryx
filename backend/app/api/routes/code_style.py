"""The code style (defined once for the installation, overridable per Workspace and repository).

- ``GET/PUT /api/v1/admin/code-style`` — platform admins: the installation's profile; GET also returns the built-in
  defaults under it;
- ``GET/PUT /api/v1/workspaces/{id}/code-style`` — members read, Workspace admins/owners write;
- ``GET/PUT /api/v1/workspaces/{id}/repositories/{repo}/code-style`` — the same for one repository of the Workspace;
- ``GET …/code-style/effective?repository=&language=`` — what applies, field by field with its source (the admin
  UI's preview "what applies to this repository").

A PUT replaces the level's whole profile (the UI sends the form); an empty body clears the level.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_style.schema_values import LANGUAGES, CodeStyleError

from ...db import get_db
from ...models import Project, User
from ...models.runtime.code_intelligence import CodeRepository
from ...services.access_control import get_project_role_for_user
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.code_style import store
from ...services.code_style.defaults import BUILT_IN
from ...services.code_style.resolve import effective

router = APIRouter(tags=["code-style"])


def _refusal(reason: str, status: int, path: str | None = None) -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": reason, **({"path": path} if path else {})}, status_code=status)


async def _workspace(db: AsyncSession, user: User, project_id: str) -> tuple[Project | None, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    return project, role in {"admin", "owner"}


async def _repository(db: AsyncSession, project_id: str, repository_id: str) -> CodeRepository | None:
    return (await db.execute(select(CodeRepository).where(
        CodeRepository.id == repository_id, CodeRepository.project_id == project_id))).scalar_one_or_none()


@router.get("/api/v1/admin/code-style")
async def get_installation_style(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    from ...services.engineering_knowledge.stacks import for_project

    # The stacks (manifests, build folders, l10n catalogs) as they apply on this installation, read only here: they
    # change through the system config ``stacks`` and a Workspace's ``config.stacks``.
    return {"profile": await store.installation_profile(db), "built_in": BUILT_IN, "languages": list(LANGUAGES),
            "stacks": await for_project(db, None)}


@router.put("/api/v1/admin/code-style")
async def put_installation_style(body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user),
                                 db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    try:
        profile = await store.set_installation_profile(db, body or None, actor_id=current_user.id)
    except CodeStyleError as error:
        return _refusal(error.reason, 400, error.path)
    await db.commit()
    return {"profile": profile}


@router.get("/api/v1/workspaces/{project_id}/code-style")
async def get_workspace_style(project_id: str, current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    return {"profile": store.workspace_profile(project), "can_edit": can_edit}


@router.put("/api/v1/workspaces/{project_id}/code-style")
async def put_workspace_style(project_id: str, body: dict[str, Any] = Body(...),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if not can_edit:
        return _refusal("workspace_admin_required", 403)
    try:
        profile = await store.set_workspace_profile(db, project, body or None, actor_id=current_user.id)
    except CodeStyleError as error:
        return _refusal(error.reason, 400, error.path)
    await db.commit()
    return {"profile": profile, "can_edit": True}


@router.get("/api/v1/workspaces/{project_id}/repositories/{repository_id}/code-style")
async def get_repository_style(project_id: str, repository_id: str, current_user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    record = await _repository(db, project_id, repository_id) if project is not None else None
    if record is None:
        return _refusal("repository_not_found", 404)
    return {"profile": store.repository_profile(record), "can_edit": can_edit}


@router.put("/api/v1/workspaces/{project_id}/repositories/{repository_id}/code-style")
async def put_repository_style(project_id: str, repository_id: str, body: dict[str, Any] = Body(...),
                               current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, can_edit = await _workspace(db, current_user, project_id)
    record = await _repository(db, project_id, repository_id) if project is not None else None
    if record is None:
        return _refusal("repository_not_found", 404)
    if not can_edit:
        return _refusal("workspace_admin_required", 403)
    try:
        profile = await store.set_repository_profile(db, record, body or None, actor_id=current_user.id)
    except CodeStyleError as error:
        return _refusal(error.reason, 400, error.path)
    await db.commit()
    return {"profile": profile, "can_edit": True}


@router.get("/api/v1/workspaces/{project_id}/code-style/effective")
async def get_effective_style(project_id: str, repository: str | None = Query(None, max_length=64),
                              language: str | None = Query(None, max_length=20),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project, _can_edit = await _workspace(db, current_user, project_id)
    if project is None:
        return _refusal("workspace_not_found", 404)
    if language and language not in LANGUAGES:
        return _refusal("unknown_language", 400)
    record = await _repository(db, project_id, repository) if repository else None
    if repository and record is None:
        return _refusal("repository_not_found", 404)
    view = effective(await store.levels(db, project=project, record=record), language or None)
    return {"project_id": project_id, "repository_id": repository, "language": language, "effective": view}
