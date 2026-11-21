"""The Instance's default workspace: the one people land in when they have not chosen one.

An administrator sets it (``POST /api/v1/projects/{id}/make-default``); it is stored as one
``SystemConfig`` value. It is only a starting point: a workspace in the URL, a person's own last
choice and an existing chat's workspace all take precedence. An archived or unknown workspace is
never answered as the default, so a stale value simply means "no default".
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ..system_config.values import get_system_config_value, set_system_config_value

DEFAULT_WORKSPACE_KEY = "workspace.default_id"


async def default_workspace_id(db: AsyncSession) -> str | None:
    """The configured default workspace, when it still exists and is active."""
    configured = await get_system_config_value(db, DEFAULT_WORKSPACE_KEY)
    if not configured:
        return None
    active = (
        await db.execute(select(Project.id).where(Project.id == configured, Project.is_active.is_(True)))
    ).scalar_one_or_none()
    return str(active) if active else None


async def set_default_workspace(db: AsyncSession, *, project_id: str, actor_id: str) -> Project:
    """Make an active workspace the Instance default; the caller commits."""
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if not project.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Restore the workspace before making it the default"
        )
    await set_system_config_value(
        db,
        key=DEFAULT_WORKSPACE_KEY,
        value=project.id,
        description="Workspace people start in when they have not chosen one",
        updated_by=actor_id,
        change_source="default_workspace",
        record_prompt_revision=False,
    )
    return project


async def refuse_if_default(db: AsyncSession, project_id: str, action: str) -> None:
    """Archiving or deleting the default would leave everyone without a start; refuse it."""
    if await default_workspace_id(db) == project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This is the default workspace. Make another workspace the default before you {action} it.",
        )


__all__ = ["DEFAULT_WORKSPACE_KEY", "default_workspace_id", "refuse_if_default", "set_default_workspace"]
