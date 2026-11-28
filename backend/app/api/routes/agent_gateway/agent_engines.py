"""Coding engine settings: Claude Code or Codex, per platform, Workspace and person."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, User
from ....services.access_control import get_project_role_for_user
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.agent_gateway.engine_keys import ENGINES, EnginePolicyError
from ....services.agent_gateway.engine_policy import (
    effective_engine,
    platform_default,
    set_person_choice,
    set_platform_default,
    set_workspace_engines,
    workspace_section,
)
from ....services.auth import get_current_user

router = APIRouter(tags=["agent-engines"])
WORKSPACE_PATH = "/api/v1/workspaces/{project_id}/agent-gateway/engines"
ADMIN_ROLES = frozenset({"admin", "owner"})


def _invalid(error: EnginePolicyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"errors": [{"code": error.reason, "field": error.path}]})


async def _workspace(db: AsyncSession, user: User, project_id: str, *, write: bool) -> tuple[Project, bool]:
    role = await get_project_role_for_user(db, user.id, project_id)
    project = await db.get(Project, project_id) if role is not None else None
    if project is None:
        raise HTTPException(status_code=404, detail={"reason": "workspace_not_found"})
    can_edit = role in ADMIN_ROLES
    if write and not can_edit:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")
    return project, can_edit


async def _workspace_payload(db: AsyncSession, user: User, project: Project, can_edit: bool) -> dict[str, Any]:
    section = workspace_section(project.config)
    setting = await effective_engine(db, user_id=user.id, workspace_id=project.id)
    return {"project_id": project.id, "engines": list(ENGINES),
            "workspace": {"allowed": list(setting.allowed), "default": (section or {}).get("default")},
            "source": "workspace" if section is not None else "default",
            "effective": setting.as_dict(), "can_edit": can_edit}


@router.get("/api/v1/admin/local-models")
async def get_local_models(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The platform's local model licence switch (``agent_gateway.local_models``)."""
    from ....services.agent_gateway.local_models import permissive_only

    return {"permissive_only": await permissive_only(db), "can_edit": await is_global_admin(db, current_user.id)}


@router.put("/api/v1/admin/local-models")
async def put_local_models(
    body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    from ....services.agent_gateway.local_models import set_permissive_only

    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Platform admin required")
    if set(body) != {"permissive_only"}:
        raise HTTPException(status_code=422, detail={"errors": [{"code": "unknown_setting"}]})
    try:
        value = await set_permissive_only(db, value=body.get("permissive_only"), actor_id=current_user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail={"errors": [{"code": "invalid_flag"}]}) from None
    await db.commit()
    return {"permissive_only": value, "can_edit": True}


@router.get("/api/v1/admin/agent-engine")
async def get_platform_engine(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"default": await platform_default(db), "engines": list(ENGINES),
            "can_edit": await is_global_admin(db, current_user.id)}


@router.put("/api/v1/admin/agent-engine")
async def put_platform_engine(
    body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Platform admin required")
    try:
        await set_platform_default(db, engine=body.get("default"), actor_id=current_user.id)
    except EnginePolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    return {"default": await platform_default(db), "engines": list(ENGINES), "can_edit": True}


@router.get(WORKSPACE_PATH)
async def get_workspace_engines(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return await _workspace_payload(db, current_user, project, can_edit)


@router.put(WORKSPACE_PATH)
async def put_workspace_engines(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    value = {key: body[key] for key in ("allowed", "default") if key in body and body[key] is not None}
    try:
        await set_workspace_engines(db, project=project, value=value, actor_id=current_user.id)
    except EnginePolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    await db.refresh(project)
    return await _workspace_payload(db, current_user, project, can_edit)


@router.put(WORKSPACE_PATH + "/me")
async def put_own_engine(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    try:
        await set_person_choice(db, user_id=current_user.id, engine=body.get("engine"), workspace_id=project.id)
    except EnginePolicyError as error:
        raise _invalid(error) from None
    await db.commit()
    return await _workspace_payload(db, current_user, project, can_edit)


__all__ = ["router"]
