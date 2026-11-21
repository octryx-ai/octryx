"""Who sees which problems (the rules every admin list applies).

- ``/admin/problems``: a platform admin sees every Workspace and the platform-wide objects; a Workspace admin or
  owner sees only the Workspaces they administer (the list is filtered, not refused); anyone else is refused.
- ``/workspaces/{id}/problems``: any member of that Workspace sees that Workspace's problems; platform-wide objects
  are never part of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import PROJECT_ADMIN_ROLES, is_global_admin
from ..project.service import get_project_access_details


class ProblemsAccessError(Exception):
    """The caller may not read these problems: ``status`` 403 (no admin) or 404 (not a member)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class ProblemScope:
    """``workspace_ids`` ``None`` = everything (platform admin without a Workspace filter)."""

    workspace_ids: frozenset[str] | None


async def admin_scope(db: AsyncSession, user: User, workspace_id: str | None) -> ProblemScope:
    if await is_global_admin(db, user.id):
        return ProblemScope(frozenset({workspace_id}) if workspace_id else None)
    administered = frozenset(
        str(item["id"]) for item in await get_project_access_details(user.id, db)
        if PROJECT_ADMIN_ROLES.intersection(str(role) for role in (item.get("project_roles") or [item.get("role")]))
    )
    if not administered:
        raise ProblemsAccessError(403, "admin_required", "Only platform or Workspace admins can see problems.")
    return ProblemScope(administered & {workspace_id} if workspace_id else administered)


async def workspace_scope(db: AsyncSession, user: User, workspace_id: str) -> ProblemScope:
    if await get_project_role_for_user(db, user.id, workspace_id) is None:
        raise ProblemsAccessError(404, "workspace_not_found", "This Workspace does not exist or you are not a member.")
    return ProblemScope(frozenset({workspace_id}))


__all__ = ["ProblemScope", "ProblemsAccessError", "admin_scope", "workspace_scope"]
