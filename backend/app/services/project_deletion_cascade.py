"""What a project soft delete deactivates beyond the project row itself.

A soft-deleted project (``is_active = false``) keeps its rows, so everything bound to it must be
switched off explicitly or it would keep acting: the project's Knowledge source connectors are
paused with their schedule off (``knowledge/sources/sync/removal.py``, audited per connector).

The resolution paths refuse anything scoped to an inactive project on their own
(``project_activity.py``), so this cascade is the durable state, not the only guard. It runs in the
caller's transaction; the route commits. The project deletion itself is audited here with the ids
it deactivated.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog, User
from .knowledge.sources.sync.removal import deactivate_workspace_connectors

PROJECT_SOFT_DELETED_AUDIT_ACTION = "project.soft_deleted"


async def deactivate_project_bindings(db: AsyncSession, *, project_id: str, actor: User) -> dict[str, Any]:
    paused_connector_ids = await deactivate_workspace_connectors(db, project_id=project_id, actor_id=actor.id)
    outcome = {"paused_knowledge_connector_ids": paused_connector_ids}
    db.add(
        AuditLog(
            user_id=actor.id,
            action=PROJECT_SOFT_DELETED_AUDIT_ACTION,
            resource_type="project",
            resource_id=project_id,
            details=outcome,
        )
    )
    await db.flush()
    return outcome
