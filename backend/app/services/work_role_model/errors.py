"""Errors and who-may-edit checks of the work-role admin API."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User

PLATFORM_ADMIN = "a platform admin"
WORKSPACE_ADMIN = "a Workspace admin or a person with the function 'Assign roles' in this Workspace"


class WorkRoleError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **extra: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra

    def http(self) -> HTTPException:
        return HTTPException(self.status, detail={"code": self.code, "message": self.message, **self.extra})


def version_conflict(kind: str) -> WorkRoleError:
    return WorkRoleError("version_conflict", f"The {kind} changed meanwhile; read it again.", 409)


async def is_platform_admin(db: AsyncSession, user: User) -> bool:
    from ..admin.governance.admin_access_service import is_global_admin

    return await is_global_admin(db, user.id)


async def require_platform_admin(db: AsyncSession, user: User, setting: str) -> None:
    if not await is_platform_admin(db, user):
        raise WorkRoleError("forbidden", f"Only a platform admin changes {setting}.", 403, setting=setting,
                            who_can_change=PLATFORM_ADMIN)


async def may_admin_workspace(db: AsyncSession, user: User, workspace_id: str) -> bool:
    """Workspace admin/owner (as for every Workspace setting), a platform admin, or the function ``assign_roles``."""
    from ..access_control import get_project_role_for_user
    from .effective import held_roles_by_user
    from .seeds import ASSIGN_ROLES

    if await is_platform_admin(db, user):
        return True
    if await get_project_role_for_user(db, user.id, workspace_id) in {"admin", "owner"}:
        return True
    held = (await held_roles_by_user(db, workspace_id, [user.id]))[user.id]
    return any(ASSIGN_ROLES in role.functions for role in held)


async def require_workspace_admin(db: AsyncSession, user: User, workspace_id: str, setting: str) -> None:
    if not await may_admin_workspace(db, user, workspace_id):
        raise WorkRoleError("forbidden", f"Only {WORKSPACE_ADMIN} changes {setting}.", 403, setting=setting,
                            who_can_change=WORKSPACE_ADMIN)


async def require_scope_admin(db: AsyncSession, user: User, workspace_id: str | None, setting: str) -> None:
    """Global roles and functions: platform admins; Workspace-scoped ones: that Workspace's admins too."""
    if workspace_id is None:
        await require_platform_admin(db, user, setting)
    else:
        await require_workspace_admin(db, user, workspace_id, setting)


__all__ = ["PLATFORM_ADMIN", "WORKSPACE_ADMIN", "WorkRoleError", "is_platform_admin", "may_admin_workspace",
           "require_platform_admin", "require_scope_admin", "require_workspace_admin", "version_conflict"]
