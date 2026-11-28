"""Who may see and change which connection: the rules every connections endpoint applies."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, User
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import is_global_admin
from .contract import (
    AVAILABLE_ALL,
    CODE_PLATFORM_ADMIN_REQUIRED,
    CODE_WORKSPACE_ADMIN_REQUIRED,
    OWNER_WORKSPACE,
    refusal,
)

WORKSPACE_ADMIN_ROLES = frozenset({"admin", "owner"})


@dataclass(frozen=True, slots=True)
class Viewer:
    user_id: str
    platform_admin: bool
    admin_workspaces: frozenset[str]

    def can_edit(self, row: ConnectorNamedConnection, workspace_ids: frozenset[str]) -> bool:
        if self.platform_admin:
            return True
        return row.owner_kind == OWNER_WORKSPACE and row.owner_workspace_id in self.admin_workspaces

    def can_see(self, row: ConnectorNamedConnection, workspace_ids: frozenset[str]) -> bool:
        if self.platform_admin:
            return True
        if row.owner_workspace_id in self.admin_workspaces:
            return True
        return row.available_in == AVAILABLE_ALL or bool(workspace_ids & self.admin_workspaces)

    def can_edit_workspace(self, workspace_id: str) -> bool:
        return self.platform_admin or workspace_id in self.admin_workspaces


async def admin_viewer(db: AsyncSession, user: User) -> Viewer:
    if await is_global_admin(db, user.id):
        return Viewer(user_id=user.id, platform_admin=True, admin_workspaces=frozenset())
    from ..project.service import get_project_access_details

    access = await get_project_access_details(user.id, db)
    admin_of = frozenset(str(item["id"]) for item in access if str(item.get("role")) in WORKSPACE_ADMIN_ROLES)
    if not admin_of:
        raise refusal(403, CODE_PLATFORM_ADMIN_REQUIRED, "Connections are managed by platform or Workspace admins.")
    return Viewer(user_id=user.id, platform_admin=False, admin_workspaces=admin_of)


async def workspace_viewer(db: AsyncSession, user: User, workspace_id: str) -> tuple[Viewer, str]:
    role = await get_project_role_for_user(db, user.id, workspace_id)
    if role is None:
        raise refusal(403, CODE_WORKSPACE_ADMIN_REQUIRED, "Only members of this Workspace see its connections.")
    platform_admin = await is_global_admin(db, user.id)
    admin_of = frozenset({workspace_id}) if str(role) in WORKSPACE_ADMIN_ROLES else frozenset()
    return Viewer(user_id=user.id, platform_admin=platform_admin, admin_workspaces=admin_of), str(role)


def require_workspace_admin(viewer: Viewer, workspace_id: str) -> None:
    if not viewer.can_edit_workspace(workspace_id):
        raise refusal(403, CODE_WORKSPACE_ADMIN_REQUIRED,
                      "Only this Workspace's admins set or reset its deviation.")


__all__ = ["Viewer", "admin_viewer", "require_workspace_admin", "workspace_viewer"]
