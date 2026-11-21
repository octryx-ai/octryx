"""Who may author or run an agent-chain template.

A template belongs to a Workspace (``project_id``) or to the platform (``project_id`` NULL):

* a Workspace template: create, update, delete and run require membership of that Workspace;
  moving a template to another Workspace also requires membership of the target;
* a platform template: every mutation and run requires the global admin role, since it is
  visible to every Workspace.

An unknown template answers 404 before any access decision.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentChainTemplate, User
from ..access_control import require_project_access
from ..notification_delivery import require_admin_user


async def require_template_scope(db: AsyncSession, user: User, project_id: str | None) -> None:
    """Membership of ``project_id``, or the global admin role for the platform scope."""
    if str(project_id or "").strip():
        await require_project_access(db, user.id, project_id)
        return
    await require_admin_user(db, user)


async def require_template_access(db: AsyncSession, user: User, template_id: str) -> AgentChainTemplate:
    """The template, once ``user`` may act on its scope; 404 for an unknown id."""
    template = await db.get(AgentChainTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Agent chain template not found")
    await require_template_scope(db, user, template.project_id)
    return template


__all__ = ["require_template_access", "require_template_scope"]
