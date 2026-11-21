"""Whether Knowledge is enabled for a Workspace, and enabling it where connectors need it.

A Source Sync connector projects into the Workspace's Evidence index, so configuring a connector
and "Run now" ensure Knowledge is enabled first, through the one governed path
(:func:`enable_workspace_knowledge`, the same as ``POST /knowledge/enable``: idempotent, audited).

The state shown is the last recorded enablement (its audit row): ``ready`` or ``needs_configuration``,
with its closed outcome and time, or ``unknown`` when nobody has enabled Knowledge through the
product yet. Only a non-``ready`` state triggers a new enablement.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog
from ..access.authorization import AuthorizedWorkspace
from ..sources.sync.utc import utc_iso
from .workspace_provisioning import (
    AUDIT_ACTION,
    STATE_NEEDS_CONFIGURATION,
    STATE_READY,
    enable_workspace_knowledge,
)

STATE_UNKNOWN = "unknown"
_KNOWN_STATES = frozenset({STATE_READY, STATE_NEEDS_CONFIGURATION})


async def knowledge_state(db: AsyncSession, project_id: str) -> dict[str, str | None]:
    """The last recorded enablement of the Workspace: ``{state, outcome, checked_at}``."""
    row = (
        await db.execute(
            select(AuditLog.details, AuditLog.created_at)
            .where(AuditLog.action == AUDIT_ACTION, AuditLog.resource_id == project_id)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).first()
    details = row.details if row is not None and isinstance(row.details, dict) else {}
    state = details.get("state")
    if state not in _KNOWN_STATES:
        return {"state": STATE_UNKNOWN, "outcome": None, "checked_at": None}
    outcome = details.get("outcome")
    return {
        "state": state,
        "outcome": outcome if isinstance(outcome, str) else None,
        "checked_at": utc_iso(row.created_at),
    }


async def ensure_knowledge_enabled(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, actor_id: str
) -> dict[str, str | None]:
    """Enable Knowledge unless the last enablement is ``ready``; answer the resulting state."""
    current = await knowledge_state(db, authorized.project_id)
    if current["state"] == STATE_READY:
        return current
    await enable_workspace_knowledge(db, authorized=authorized, actor_id=actor_id)
    return await knowledge_state(db, authorized.project_id)


__all__ = ["STATE_UNKNOWN", "ensure_knowledge_enabled", "knowledge_state"]
