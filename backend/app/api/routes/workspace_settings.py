"""Workspace settings sections with their own editor. Transport only; the logic is
``services/workspace_settings/rules.py``. Workspace admins and owners, and platform admins.

- ``GET|PUT /api/v1/admin/workspaces/{id}/coding`` — ``{requires_governed_routing, tool_rules, client_deny}``.
- ``GET /api/v1/admin/workspaces/{id}/tools`` — the Workspace tool policy the dispatch enforces, read-only
  (``{source, policy}``; audit S-D11, review finding 4).
- ``GET|PUT /api/v1/admin/workspaces/{id}/budget`` — ``{session_usd, request_usd, per_person_daily_usd}``; ``null``
  inherits the platform value.

Refusals: 422 ``{code, path, reason}``; 403 ``{code: platform_admin_required, path, reason}`` when a Workspace
admin or owner would loosen a platform value (``services/workspace_settings/bounds.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Project, User
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.tool_access_policy_config import project_tool_visibility_view
from ...services.workspace_settings.bounds import LooseningRefusedError
from ...services.workspace_settings.rules import (
    WorkspaceSettingsError,
    budget_view,
    coding_view,
    save_budget,
    save_coding,
)
from .workspace_models import require_workspace_admin

router = APIRouter(prefix="/api/v1/admin/workspaces", tags=["workspace-settings"])


async def _project(db: AsyncSession, user: User, project_id: str) -> Project:
    await require_workspace_admin(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return project


async def _save(db: AsyncSession, action: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    try:
        view = await action()
    except WorkspaceSettingsError as error:
        await db.rollback()
        raise HTTPException(status_code=422, detail={"code": error.code, "path": error.path,
                                                     "reason": error.reason}) from None
    except LooseningRefusedError as error:
        await db.rollback()
        raise HTTPException(status_code=403, detail={"code": error.code, "path": error.path,
                                                     "reason": error.reason}) from None
    await db.commit()
    return view


@router.get("/{project_id}/coding")
async def get_coding(project_id: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return coding_view(await _project(db, user, project_id))


@router.put("/{project_id}/coding")
async def put_coding(project_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await _project(db, user, project_id)
    admin = await is_global_admin(db, user.id)
    return await _save(db, lambda: save_coding(db, project, body, actor_id=user.id, platform_admin=admin))


@router.get("/{project_id}/budget")
async def get_budget(project_id: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await budget_view(db, await _project(db, user, project_id))


@router.put("/{project_id}/budget")
async def put_budget(project_id: str, body: dict[str, Any] = Body(...), user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await _project(db, user, project_id)
    admin = await is_global_admin(db, user.id)
    return await _save(db, lambda: save_budget(db, project, body, actor_id=user.id, platform_admin=admin))


__all__ = ["router"]


@router.get("/{project_id}/tools")
async def get_tool_visibility(project_id: str, user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await _project(db, user, project_id)
    return project_tool_visibility_view(dict(project.config or {}))
