"""What a person may let their Claude Code sessions do, by their role in the Workspace."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ...models.security.user import UserProject
from ..access_control import get_project_role_for_user

CEILING_READ_ONLY = "read_only"
CEILING_EDIT = "edit"
CEILING_BYPASS = "bypass"
_RANK = {CEILING_READ_ONLY: 0, CEILING_EDIT: 1, CEILING_BYPASS: 2}
MODES_BY_CEILING = {
    CEILING_READ_ONLY: ("plan",),
    CEILING_EDIT: ("plan", "default", "acceptEdits"),
    CEILING_BYPASS: ("plan", "default", "acceptEdits", "bypassPermissions"),
}
REASON_BYPASS_OWNER_ONLY = "bypass_requires_workspace_owner"


DEFAULT_ROLE_CEILINGS = {"viewer": CEILING_READ_ONLY, "member": CEILING_EDIT, "owner": CEILING_BYPASS,
                         "admin": CEILING_BYPASS}


def role_ceilings(project: Project | None) -> dict[str, str]:
    policy = (project.config or {}).get("agent_gateway_policy") if project is not None else None
    stored = policy.get("role_modes") if isinstance(policy, dict) else None
    ceilings = dict(DEFAULT_ROLE_CEILINGS)
    if isinstance(stored, dict):
        ceilings.update({role: value for role, value in stored.items()
                         if role in ceilings and value in _RANK})
    return ceilings


def role_ceiling(role: str | None, ceilings: dict[str, str] | None = None) -> str:
    table = ceilings or DEFAULT_ROLE_CEILINGS
    role = "member" if role == "editor" else role
    return table.get(role or "", CEILING_READ_ONLY)  # an unknown role, or none, reads only


def workspace_ceiling(project: Project | None) -> str:
    policy = (project.config or {}).get("agent_gateway_policy") if project is not None else None
    if not isinstance(policy, dict):
        return CEILING_BYPASS
    if policy.get("free_sessions") == "read_only":
        return CEILING_READ_ONLY
    if policy.get("bypass_permissions") == "disabled":
        return CEILING_EDIT
    return CEILING_BYPASS


async def session_ceiling(db: AsyncSession, *, user_id: str | None, workspace_id: str | None) -> str:
    if not workspace_id or not user_id:
        return CEILING_READ_ONLY
    project = await db.get(Project, workspace_id)
    role = await get_project_role_for_user(db, user_id, workspace_id)
    if role == "admin":  # a platform admin: the shortcut hides their membership; an owner by membership is an owner
        membership = await db.get(UserProject, (user_id, workspace_id))
        role = "owner" if membership is not None and membership.role == "owner" else "admin"
    return min(role_ceiling(role, role_ceilings(project)), workspace_ceiling(project), key=_RANK.__getitem__)


def allowed_modes(ceiling: str) -> list[str]:
    return list(MODES_BY_CEILING.get(ceiling, MODES_BY_CEILING[CEILING_READ_ONLY]))


__all__ = [
    "CEILING_BYPASS",
    "CEILING_EDIT",
    "CEILING_READ_ONLY",
    "REASON_BYPASS_OWNER_ONLY",
    "DEFAULT_ROLE_CEILINGS",
    "allowed_modes",
    "role_ceiling",
    "role_ceilings",
    "session_ceiling",
    "workspace_ceiling",
]
