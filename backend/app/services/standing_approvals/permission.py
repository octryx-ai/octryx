"""Who may grant a standing approval ("Always for this Workspace"): Workspace admins and owners."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..access_control import get_project_role_for_user

STANDING_GRANT_ROLES = frozenset({"admin", "owner"})


async def can_grant_standing_approval(db: AsyncSession, *, user_id: str | None, project_id: str | None) -> bool:
    if not user_id or not project_id:
        return False
    return await get_project_role_for_user(db, str(user_id), str(project_id)) in STANDING_GRANT_ROLES


async def require_standing_grant_permission(db: AsyncSession, *, user_id: str, project_id: str | None) -> str:
    if not project_id:
        raise HTTPException(status_code=400, detail="Always for this Workspace needs a Workspace session")
    if not await can_grant_standing_approval(db, user_id=user_id, project_id=project_id):
        raise HTTPException(status_code=403, detail="Project admin or owner role required for this action.")
    return str(project_id)


__all__ = ["STANDING_GRANT_ROLES", "can_grant_standing_approval", "require_standing_grant_permission"]
