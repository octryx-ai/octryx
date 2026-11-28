"""Workspace authorization of a registry API (read = any role, author = admin or owner). An unknown Workspace and one
without a role answer the same 404."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, User
from .access_control import get_project_role_for_user

WORKSPACE_NOT_FOUND_DETAIL = "Workspace not found"
AUTHOR_ROLE_REQUIRED_DETAIL = "Project admin or owner role required for this action."
AUTHOR_PROJECT_ROLES = frozenset({"admin", "owner"})


async def authorize_workspace(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: str,
    require_author: bool,
    not_found_detail: Any = WORKSPACE_NOT_FOUND_DETAIL,
) -> str:
    # ``not_found_detail`` answers an out-of-scope row with exactly the body of an unknown one.
    project_id = str(workspace_id or "").strip()
    exists = (
        (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
        if project_id
        else None
    )
    if exists is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    role = await get_project_role_for_user(db, current_user.id, project_id)
    if role is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    if require_author and role not in AUTHOR_PROJECT_ROLES:
        raise HTTPException(status_code=403, detail=AUTHOR_ROLE_REQUIRED_DETAIL)
    return project_id


__all__ = ["AUTHOR_PROJECT_ROLES", "authorize_workspace"]
