"""Who may author or run an agent-chain template."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentChainTemplate, User
from ..access_control import require_project_access
from ..notification_delivery import require_admin_user


async def require_template_scope(db: AsyncSession, user: User, project_id: str | None) -> None:
    if str(project_id or "").strip():
        await require_project_access(db, user.id, project_id)
        return
    await require_admin_user(db, user)


async def require_template_access(db: AsyncSession, user: User, template_id: str) -> AgentChainTemplate:
    template = await db.get(AgentChainTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Agent chain template not found")
    await require_template_scope(db, user, template.project_id)
    return template


__all__ = ["require_template_access", "require_template_scope"]
