"""Action-needed items of the handoff flow: takeovers to confirm and handoffs to pick up.

- ``handoff_confirm``: a pending, unexpired takeover addressed to me (``to_user``), or, when it came from an
  automatic handoff request, any takeover in a Workspace where I am admin/owner.
  ``{kind, project, takeover_id, work_item, agent:{user, agent_hash} (the requester), created_at}``.
- ``available_handoff``: a live claim with an automatic handoff request in one of my Workspaces, not my own,
  offered only while my own agent sessions there have spare allowance (below 80% or unknown). The item shows
  no allowance numbers. ``{kind, project, claim_id, work_item, agent:{user, agent_hash} (the holder),
  created_at}``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, WorkItem, WorkItemTakeover
from ...time_utils import utc_now
from .automation import available_claims, has_spare_allowance
from .claim_values import iso
from .envelope import user_refs
from .takeover_status import STATUS_PENDING

ITEM_HANDOFF_CONFIRM = "handoff_confirm"
ITEM_AVAILABLE_HANDOFF = "available_handoff"


async def handoff_confirm_items(
    db: AsyncSession, user_id: str, projects: dict[str, dict[str, Any]], admin_projects: set[str]
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(WorkItemTakeover, WorkItem)
            .join(WorkItem, WorkItem.id == WorkItemTakeover.work_item_id)
            .where(
                WorkItemTakeover.project_id.in_(sorted(projects)),
                WorkItemTakeover.status == STATUS_PENDING,
                WorkItemTakeover.expires_at > utc_now(),
            )
        )
    ).all()
    mine = [
        (takeover, item) for takeover, item in rows
        if takeover.to_user_id == user_id or (takeover.automatic and takeover.project_id in admin_projects)
    ]
    users = await user_refs(db, [takeover.to_user_id for takeover, _ in mine])
    return [
        {
            "kind": ITEM_HANDOFF_CONFIRM,
            "project": projects[takeover.project_id],
            "takeover_id": takeover.id,
            "work_item": {"id": item.id, "key": item.source_key, "title": item.title},
            "agent": {"user": users.get(takeover.to_user_id), "agent_hash": takeover.to_agent_hash},
            "created_at": iso(takeover.created_at),
        }
        for takeover, item in mine
    ]


async def available_handoff_items(
    db: AsyncSession, user_id: str, projects: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    offered = [entry for entry in await available_claims(db, list(projects)) if entry[0].holder_user_id != user_id]
    if not offered:
        return []
    sessions = (
        await db.execute(
            select(AgentPresence).where(
                AgentPresence.user_id == user_id,
                AgentPresence.project_id.in_(sorted({claim.project_id for claim, _, _ in offered})),
            )
        )
    ).scalars().all()
    spare = {
        project_id: has_spare_allowance([row for row in sessions if row.project_id == project_id])
        for project_id in {claim.project_id for claim, _, _ in offered}
    }
    users = await user_refs(db, [claim.holder_user_id for claim, _, _ in offered])
    return [
        {
            "kind": ITEM_AVAILABLE_HANDOFF,
            "project": projects[claim.project_id],
            "claim_id": claim.id,
            "work_item": {"id": item.id, "key": item.source_key, "title": item.title},
            "agent": {"user": users.get(claim.holder_user_id), "agent_hash": claim.holder_ref_hash},
            "created_at": iso(requested_at),
        }
        for claim, item, requested_at in offered
        if spare[claim.project_id]
    ]


__all__ = ["ITEM_AVAILABLE_HANDOFF", "ITEM_HANDOFF_CONFIRM", "available_handoff_items", "handoff_confirm_items"]
