"""Who sees and who edits an agent definition.

Agents are shared in their Workspace, not per owner:

- **visible** to its owner, to every member of its Workspace, to everyone when it is global (no
  Workspace) or built-in, and to global admins;
- **editable** by its owner, by an admin or owner of its Workspace and by global admins; a built-in
  agent only by global admins.

The membership comes from ``project.service.get_project_access_details`` (direct and group grants),
the same source every Workspace check reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinition
from .admin.governance.admin_access_service import is_global_admin

WORKSPACE_EDITOR_ROLES = frozenset({"admin", "owner"})


@dataclass(frozen=True, slots=True)
class AgentAccess:
    user_id: str
    global_admin: bool
    project_ids: frozenset[str]
    editor_project_ids: frozenset[str]

    def visible_clause(self) -> ColumnElement[bool]:
        if self.global_admin:
            return true()
        return or_(
            AgentDefinition.owner_id == self.user_id,
            AgentDefinition.project_id.is_(None),
            AgentDefinition.builtin_key.is_not(None),
            AgentDefinition.project_id.in_(sorted(self.project_ids)),
        )

    def editable_clause(self) -> ColumnElement[bool]:
        if self.global_admin:
            return true()
        return (AgentDefinition.builtin_key.is_(None)) & or_(
            AgentDefinition.owner_id == self.user_id,
            AgentDefinition.project_id.in_(sorted(self.editor_project_ids)),
        )

    def can_edit(self, agent: AgentDefinition) -> bool:
        if self.global_admin:
            return True
        if agent.builtin_key:
            return False
        return agent.owner_id == self.user_id or (agent.project_id or "") in self.editor_project_ids


def _workspace_editor(access: dict) -> bool:
    roles = access.get("project_roles") or [access.get("role")]
    return any(str(role or "").lower() in WORKSPACE_EDITOR_ROLES for role in roles)


async def agent_access(db: AsyncSession, user_id: str) -> AgentAccess:
    from .project.service import get_project_access_details

    admin = await is_global_admin(db, user_id)
    projects = await get_project_access_details(user_id, db) if not admin else []
    return AgentAccess(
        user_id=user_id,
        global_admin=admin,
        project_ids=frozenset(str(item["id"]) for item in projects),
        editor_project_ids=frozenset(str(item["id"]) for item in projects if _workspace_editor(item)),
    )


async def visible_agent_clause(db: AsyncSession, user_id: str) -> ColumnElement[bool]:
    return (await agent_access(db, user_id)).visible_clause()


def workspace_agent_clause(project_id: str) -> ColumnElement[bool]:
    """A turn in a Workspace runs only global, built-in and that Workspace's agents (never another one's)."""
    return or_(
        AgentDefinition.project_id.is_(None),
        AgentDefinition.builtin_key.is_not(None),
        AgentDefinition.project_id == project_id,
    )


async def editable_agent_clause(db: AsyncSession, user_id: str) -> ColumnElement[bool]:
    return (await agent_access(db, user_id)).editable_clause()


__all__ = [
    "WORKSPACE_EDITOR_ROLES",
    "AgentAccess",
    "agent_access",
    "editable_agent_clause",
    "visible_agent_clause",
    "workspace_agent_clause",
]
