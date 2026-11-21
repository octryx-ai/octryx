"""Command safety: one page, one payload for the command risk gate. Transport only; the contract
lives in ``services/command_safety/settings.py``. Platform admins only.

- ``GET /api/v1/admin/command-safety`` — the platform gate (checks, AI risk review, command lists, guard rules) and
  every active Workspace's *Inherit* / *Override* with its differences.
- ``PUT /api/v1/admin/command-safety`` ``{checks: {key: bool}, llm_risk: {timeout_seconds, review_threshold,
  deny_threshold}, lists: {always_deny_patterns, commands, git, kubectl, operators}, guard_rules?: {id: bool},
  custom_guard_rules?: {id: bool}}`` — both stores in one transaction; 422 ``{code, path}`` when invalid.
- ``GET|PUT /api/v1/admin/command-safety/workspaces/{id}`` — ``{mode: inherit}`` or ``{mode: override, settings}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.command_safety.contract import CommandSafetyError
from app.services.command_safety.reading import platform_settings, workspace_overview, workspace_settings
from app.services.command_safety.writing import save_platform_settings, save_workspace_settings

from ...db import get_db
from ...models import Project, User
from .policy_engine import require_admin

router = APIRouter(prefix="/api/v1/admin/command-safety", tags=["command-safety"])


def _invalid(error: CommandSafetyError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "path": error.path})


async def _payload(db: AsyncSession) -> dict[str, Any]:
    return {**await platform_settings(db), "workspaces": await workspace_overview(db)}


async def _project(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return project


@router.get("")
async def get_command_safety(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await _payload(db)


@router.put("")
async def put_command_safety(body: dict[str, Any] = Body(...), user: User = Depends(require_admin),
                             db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await save_platform_settings(db, body, actor_id=user.id)
    except CommandSafetyError as error:
        raise _invalid(error) from None
    await db.commit()
    return await _payload(db)


@router.get("/workspaces/{project_id}")
async def get_workspace_command_safety(project_id: str, _: User = Depends(require_admin),
                                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await workspace_settings(db, await _project(db, project_id))


@router.put("/workspaces/{project_id}")
async def put_workspace_command_safety(project_id: str, body: dict[str, Any] = Body(...),
                                       user: User = Depends(require_admin),
                                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await _project(db, project_id)
    try:
        view = await save_workspace_settings(db, project, body, actor_id=user.id)
    except CommandSafetyError as error:
        raise _invalid(error) from None
    await db.commit()
    return view


__all__ = ["router"]
