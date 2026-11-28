"""Who sees which problems (the rules every admin list applies)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import PROJECT_ADMIN_ROLES, is_global_admin
from ..project.service import get_project_access_details
from .model import CollectContext


class ProblemsAccessError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class ProblemScope:
    workspace_ids: frozenset[str] | None
    viewer_id: str | None = None

    def context(self, now: datetime) -> CollectContext:
        return CollectContext(now=now, workspace_ids=self.workspace_ids, viewer_id=self.viewer_id)


def platform_scope(user: User, workspace_id: str | None = None) -> ProblemScope:
    return ProblemScope(frozenset({workspace_id}) if workspace_id else None, viewer_id=user.id)


async def admin_scope(db: AsyncSession, user: User, workspace_id: str | None) -> ProblemScope:
    if await is_global_admin(db, user.id):
        return platform_scope(user, workspace_id)
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


__all__ = ["ProblemScope", "ProblemsAccessError", "admin_scope", "platform_scope", "workspace_scope"]
