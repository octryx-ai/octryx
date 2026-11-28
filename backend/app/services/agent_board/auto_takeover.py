"""Automatic takeover under a Workspace's ``auto`` handoff policy."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentPresence, Notification, Project, WorkItem, WorkItemClaim, WorkItemTakeover
from ...models.worker.teaming import NotificationPreference
from ...time_utils import utc_now
from ..agent_gateway.handoff_policy_keys import MODE_AUTO, REQUESTERS_ADMINS, HandoffPolicy, handoff_policy_from_config
from ..project.service import get_project_access_details
from .claim_values import KIND_GATEWAY_SESSION, is_live
from .envelope import user_refs
from .handoffs import latest_handoff
from .messages import ADMIN_ROLES
from .takeover_status import STATUS_PENDING
from .takeovers import decide_takeover

STALE_AFTER = timedelta(minutes=10)
STATE_LIMIT_REACHED = "limit_reached"
PROFILE_GOVERNED = "governed"
INFO_NOTIFICATION_TYPE = "agent_board_info.handoff_auto"


def _hash(session_key: str) -> str:
    from ..agent_gateway.presence import session_key_hash

    return session_key_hash(session_key)


async def workspace_handoff_policy(db: AsyncSession, project_id: str) -> HandoffPolicy:
    project = await db.get(Project, project_id)
    return handoff_policy_from_config(project.config if project is not None else None)[0]


async def session_of(db: AsyncSession, project_id: str, agent_hash: str | None) -> AgentPresence | None:
    if not agent_hash:
        return None
    rows = (await db.execute(select(AgentPresence).where(AgentPresence.project_id == project_id))).scalars().all()
    return next((row for row in rows if _hash(row.session_key) == agent_hash), None)


def holder_needs_handoff(presence: AgentPresence | None, policy: HandoffPolicy) -> bool:
    if presence is None:
        return False
    if presence.state == STATE_LIMIT_REACHED or presence.stopped_at is not None:
        return True
    if presence.seven_day_pct is not None and presence.seven_day_pct >= policy.auto_threshold_pct:
        return True
    return presence.last_seen_at is None or utc_now() - presence.last_seen_at > STALE_AFTER


def requester_has_spare(presence: AgentPresence | None, policy: HandoffPolicy) -> bool:
    if presence is None or presence.stopped_at is not None or presence.state == STATE_LIMIT_REACHED:
        return False
    if presence.last_seen_at is None or utc_now() - presence.last_seen_at > STALE_AFTER:
        return False
    if presence.seven_day_pct is None:
        return presence.profile == PROFILE_GOVERNED
    return presence.seven_day_pct <= 100 - policy.require_spare_pct


async def requester_allowed(db: AsyncSession, user_id: str, project_id: str, policy: HandoffPolicy) -> bool:
    access = await get_project_access_details(user_id, db)
    role = next((entry.get("role") for entry in access if str(entry["id"]) == project_id), None)
    if role is None:
        return False
    return role in ADMIN_ROLES if policy.allowed_requesters == REQUESTERS_ADMINS else True


async def auto_conditions(db: AsyncSession, takeover: WorkItemTakeover, policy: HandoffPolicy) -> dict[str, bool]:
    claim = await db.get(WorkItemClaim, takeover.from_claim_id) if takeover.from_claim_id else None
    live = claim is not None and is_live(claim, utc_now())
    holder = await session_of(db, takeover.project_id, claim.holder_ref_hash) \
        if live and claim.holder_kind == KIND_GATEWAY_SESSION else None
    requester = await session_of(db, takeover.project_id, takeover.to_agent_hash) \
        if takeover.to_agent_kind == KIND_GATEWAY_SESSION else None
    return {
        "holder_needs_handoff": live and (claim.handed_off_at is not None or holder_needs_handoff(holder, policy)),
        "requester_has_spare": requester_has_spare(requester, policy),
        "requester_allowed": await requester_allowed(db, takeover.to_user_id, takeover.project_id, policy),
        "handoff_exists": await latest_handoff(db, takeover.work_item_id) is not None,
    }


async def _info_notifications(db: AsyncSession, takeover: WorkItemTakeover) -> None:
    item = await db.get(WorkItem, takeover.work_item_id)
    users = await user_refs(db, [takeover.from_user_id, takeover.to_user_id])

    def name(user_id: str | None) -> str:
        user = users.get(user_id) if user_id else None
        return (user or {}).get("display_name") or "another user"

    title = (f"{item.source_key if item else 'A work item'} was handed over automatically from agent of "
             f"{name(takeover.from_user_id)} to agent of {name(takeover.to_user_id)}")[:200]
    link = f"/chat?area=agents&workspace_id={takeover.project_id}&takeover_id={takeover.id}"
    for user_id in {takeover.from_user_id, takeover.to_user_id} - {None}:
        preference = await db.get(NotificationPreference, user_id)
        if preference is not None and not preference.in_app_enabled:
            continue
        db.add(Notification(id=str(uuid.uuid4()), user_id=user_id, type=INFO_NOTIFICATION_TYPE, title=title,
                            body=None, link=link, is_read=False, created_at=utc_now()))
    await db.flush()


async def maybe_auto_confirm(db: AsyncSession, takeover: WorkItemTakeover) -> bool:
    if takeover.status != STATUS_PENDING or takeover.expires_at <= utc_now() or not takeover.to_agent_hash:
        return False
    policy = await workspace_handoff_policy(db, takeover.project_id)
    if policy.mode != MODE_AUTO:
        return False
    conditions = await auto_conditions(db, takeover, policy)
    if not all(conditions.values()):
        return False
    snapshot = {**policy.as_dict(), "conditions": conditions}
    try:
        await decide_takeover(db, takeover=takeover, user_id=None, confirm=True, policy_snapshot=snapshot)
    except HTTPException as error:
        if isinstance(error.detail, dict) and error.detail.get("code") == "takeover_not_pending":
            return False  # a person decided first: exactly one decision wins
        raise
    from .takeover_effects import after_takeover_decision

    await after_takeover_decision(db, takeover, actor_user_id=takeover.to_user_id)
    await _info_notifications(db, takeover)
    return True


async def pick_requester(
    db: AsyncSession, claim: WorkItemClaim, policy: HandoffPolicy, *, exclude: frozenset[str] = frozenset()
) -> AgentPresence | None:
    sessions = (
        await db.execute(
            select(AgentPresence).where(AgentPresence.project_id == claim.project_id,
                                        AgentPresence.stopped_at.is_(None))
        )
    ).scalars().all()
    candidates = []
    for row in sessions:
        if _hash(row.session_key) in {claim.holder_ref_hash, *exclude} or row.user_id is None:
            continue
        if requester_has_spare(row, policy) and await requester_allowed(db, row.user_id, claim.project_id, policy):
            candidates.append(row)
    if not candidates:
        return None
    return min(candidates, key=lambda row: (_used(row), -(row.last_seen_at.timestamp() if row.last_seen_at else 0)))


def _used(row: AgentPresence) -> float:
    known = [value for value in (row.five_hour_pct, row.seven_day_pct) if value is not None]
    return max(known) if known else 0.0


__all__ = [
    "INFO_NOTIFICATION_TYPE",
    "STALE_AFTER",
    "auto_conditions",
    "holder_needs_handoff",
    "maybe_auto_confirm",
    "pick_requester",
    "requester_allowed",
    "requester_has_spare",
    "workspace_handoff_policy",
]
