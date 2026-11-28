"""Automatic handoff requests, available handoffs and the handoff nudge."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardMessage, AgentPresence, WorkItem, WorkItemClaim, WorkItemTakeover
from ...time_utils import utc_now
from .claim_values import KIND_GATEWAY_SESSION, iso
from .handoffs import latest_handoff

AUTO_REQUEST_SEVEN_DAY_PCT = 90.0
SPARE_BELOW_PCT = 80.0
AUTHOR_SYSTEM = "system"
STATE_LIMIT_REACHED = "limit_reached"
AUTO_BODY = (
    "Automatic handoff request: the agent session holding {key} is at or near its usage limit. "
    "A member with spare allowance may request a takeover."
)


def needs_handoff(presence: AgentPresence, threshold: float = AUTO_REQUEST_SEVEN_DAY_PCT) -> bool:
    seven_day = presence.seven_day_pct
    return presence.state == STATE_LIMIT_REACHED or (seven_day is not None and seven_day >= threshold)


async def _live_session_claims(db: AsyncSession, ref_hash: str, project_id: str) -> list[WorkItemClaim]:
    statement = select(WorkItemClaim).where(
        WorkItemClaim.holder_kind == KIND_GATEWAY_SESSION,
        WorkItemClaim.holder_ref_hash == ref_hash,
        WorkItemClaim.project_id == project_id,
        WorkItemClaim.released_at.is_(None),
        WorkItemClaim.lease_until > utc_now(),
    )
    return list((await db.execute(statement)).scalars().all())


async def request_handoffs_for_presence(db: AsyncSession, presence: AgentPresence, ref_hash: str) -> int:
    from .auto_takeover import workspace_handoff_policy

    policy = await workspace_handoff_policy(db, presence.project_id)
    auto = policy.mode == "auto"
    threshold = policy.auto_threshold_pct if auto else AUTO_REQUEST_SEVEN_DAY_PCT
    if presence.stopped_at is not None or not needs_handoff(presence, threshold):
        return 0
    created = 0
    for claim in await _live_session_claims(db, ref_hash, presence.project_id):
        item = await db.get(WorkItem, claim.work_item_id)
        offered = await make_offer(db, claim, policy) if auto and claim.offer_agent_hash is None else None
        if await post_automatic_request(db, claim, item, to_agent_hash=offered):
            created += 1
    return created


async def post_automatic_request(
    db: AsyncSession, claim: WorkItemClaim, item: WorkItem | None, *, to_agent_hash: str | None = None
) -> bool:
    exists = await db.execute(
        select(AgentBoardMessage.id).where(
            AgentBoardMessage.claim_id == claim.id, AgentBoardMessage.author_type == AUTHOR_SYSTEM
        )
    )
    if exists.first() is not None:
        return False
    message = AgentBoardMessage(
        id=str(uuid.uuid4()),
        project_id=claim.project_id,
        work_item_id=claim.work_item_id,
        author_type=AUTHOR_SYSTEM,
        author_user_id=claim.holder_user_id,
        author_agent_hash=claim.holder_ref_hash,
        on_behalf_of_user_id=claim.holder_user_id,
        kind="handoff_request",
        to_role="admins",
        to_agent_hash=to_agent_hash,
        body=AUTO_BODY.format(key=item.source_key if item else "this work item"),
        options=[],
        created_at=utc_now(),
        claim_id=claim.id,
    )
    try:
        async with db.begin_nested():
            db.add(message)
            await db.flush()
    except IntegrityError:
        return False  # another request won the race: still exactly one per claim
    return True


async def make_offer(db: AsyncSession, claim: WorkItemClaim, policy: Any) -> str | None:
    from ..agent_gateway.presence import session_key_hash
    from .auto_takeover import pick_requester

    history = [value for value in (claim.offer_history or []) if isinstance(value, str)]
    candidate = await pick_requester(db, claim, policy, exclude=frozenset(history))
    offered = session_key_hash(candidate.session_key) if candidate is not None else None
    claim.offer_agent_hash = offered
    claim.offer_at = utc_now()
    claim.offer_history = history + [offered] if offered else history
    await db.flush()
    return offered


async def refresh_offers(db: AsyncSession, project_id: str, policy: Any) -> None:
    from .takeover_status import STATUS_PENDING

    deadline = utc_now() - timedelta(minutes=policy.offer_timeout_minutes)
    stale = (
        await db.execute(
            select(WorkItemClaim).where(
                WorkItemClaim.project_id == project_id, WorkItemClaim.released_at.is_(None),
                WorkItemClaim.lease_until > utc_now(), WorkItemClaim.offer_agent_hash.is_not(None),
                WorkItemClaim.offer_at <= deadline,
            )
        )
    ).scalars().all()
    for claim in stale:
        requested = await db.execute(
            select(WorkItemTakeover.id).where(
                WorkItemTakeover.from_claim_id == claim.id, WorkItemTakeover.to_agent_hash == claim.offer_agent_hash,
                WorkItemTakeover.status == STATUS_PENDING,
            )
        )
        if requested.first() is None:
            await make_offer(db, claim, policy)


async def available_claims(db: AsyncSession, project_ids: list[str]) -> list[tuple[WorkItemClaim, WorkItem, Any]]:
    if not project_ids:
        return []
    rows = (
        await db.execute(
            select(WorkItemClaim, WorkItem, AgentBoardMessage.created_at)
            .join(AgentBoardMessage, AgentBoardMessage.claim_id == WorkItemClaim.id)
            .join(WorkItem, WorkItem.id == WorkItemClaim.work_item_id)
            .where(
                WorkItemClaim.project_id.in_(sorted(set(project_ids))),
                WorkItemClaim.released_at.is_(None),
                WorkItemClaim.lease_until > utc_now(),
                AgentBoardMessage.author_type == AUTHOR_SYSTEM,
            )
            .order_by(AgentBoardMessage.created_at.desc())
        )
    ).all()
    return [(claim, item, created_at) for claim, item, created_at in rows]


def has_spare_allowance(rows: list[AgentPresence]) -> bool:
    for row in rows:
        if row.stopped_at is not None:
            continue
        if row.state == STATE_LIMIT_REACHED:
            return False
        for value in (row.five_hour_pct, row.seven_day_pct):
            if value is not None and value >= SPARE_BELOW_PCT:
                return False
    return True


async def available_for_session(db: AsyncSession, presence: AgentPresence, ref_hash: str) -> dict[str, Any]:
    if not has_spare_allowance([presence]):
        return {"count": 0, "items": []}
    keys = [item.source_key for claim, item, _ in await available_claims(db, [presence.project_id])
            if claim.holder_ref_hash != ref_hash]
    return {"count": len(keys), "items": keys[:20]}


async def handoff_nudges(db: AsyncSession, ref_hash: str, project_id: str) -> list[dict[str, str]]:
    nudges = []
    for claim in await _live_session_claims(db, ref_hash, project_id):
        handoff = await latest_handoff(db, claim.work_item_id)
        behind = handoff is None or (claim.last_write_at is not None and claim.last_write_at > handoff.created_at)
        if not behind:
            continue
        item = await db.get(WorkItem, claim.work_item_id)
        marker = f"{claim.id}:{iso(claim.last_write_at) or '-'}:{handoff.version if handoff else 0}"
        nudges.append({"work_item_key": item.source_key if item else claim.work_item_id, "marker": marker,
                       "kind": "update"})
    return nudges


async def handoff_offers(db: AsyncSession, agent_hash: str, project_id: str) -> list[dict[str, str]]:
    claims = (
        await db.execute(
            select(WorkItemClaim).where(
                WorkItemClaim.project_id == project_id, WorkItemClaim.offer_agent_hash == agent_hash,
                WorkItemClaim.released_at.is_(None), WorkItemClaim.lease_until > utc_now(),
            )
        )
    ).scalars().all()
    offers = []
    for claim in claims:
        item = await db.get(WorkItem, claim.work_item_id)
        offers.append({"work_item_key": item.source_key if item else claim.work_item_id,
                       "marker": f"offer:{claim.id}:{iso(claim.offer_at) or '-'}", "kind": "offer"})
    return offers


__all__ = [
    "AUTO_REQUEST_SEVEN_DAY_PCT",
    "SPARE_BELOW_PCT",
    "available_claims",
    "available_for_session",
    "handoff_nudges",
    "handoff_offers",
    "make_offer",
    "refresh_offers",
    "has_spare_allowance",
    "needs_handoff",
    "request_handoffs_for_presence",
]
