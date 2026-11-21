"""Automatic handoff requests, available handoffs and the handoff nudge.

- **Automatic request** (:func:`request_handoffs_for_presence`): when a session reaches ``limit_reached`` or a
  seven-day use of at least :data:`AUTO_REQUEST_SEVEN_DAY_PCT` while it holds live claims, one ``handoff_request``
  per claim is posted (``author_type: system``, ``to_role: admins``; the author user is the holder's, since a
  board message always names a user). The partial unique index ``uq_agent_board_auto_handoff`` keeps it to one per
  claim, also under a race. The text names no allowance number.
- **Available handoffs** (:func:`available_claims`): live claims with an automatic request, offered to other
  members whose own use is below :data:`SPARE_BELOW_PCT` or unknown.
- **Offers** (:func:`make_offer`, :func:`refresh_offers`; offer, never assign): under ``auto`` the
  item is offered to the best candidate (most spare allowance, then latest heartbeat) on the claim and the
  request; the offer moves on after ``offer_timeout_minutes`` without that agent's own request. The server never
  requests or confirms a takeover for an agent that did not ask.
- **Handoff nudge** (:func:`handoff_nudges`): a gateway session's live claims whose item changed under the claim
  after the latest handoff, or that have no handoff yet. Each carries a ``marker`` that changes with every new
  write or handoff, so the Stop hook blocks once per change. An offered agent gets an ``offer`` entry.
"""

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
    """Post the automatic requests this session's state calls for; returns how many were new. Flushes.

    Under an ``auto`` handoff policy the policy's threshold applies, and the item is **offered** to the
    qualifying agent with the most spare allowance (offer, never assign). Only that agent's own
    ``work_item_takeover_request`` can lead to a takeover.
    """
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
    """The one system ``handoff_request`` of ``claim`` (addressed to the offered agent, if any); ``False`` when it
    already exists. Flushes."""
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
    """Offer the item to the next best agent (never one offered before); returns its hash or ``None``. Flushes.

    An offer only names the agent (the claim's ``offer_agent_hash``, its hook hints and the request's
    addressee). The server never requests or confirms a takeover on its behalf.
    """
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
    """An offer the offered agent did not take up within ``offer_timeout_minutes`` moves to the next candidate."""
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
    """``(claim, item, request created_at)`` for live claims with an automatic handoff request."""
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
    """Below :data:`SPARE_BELOW_PCT` on every known window of every active session; unknown counts as spare."""
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
    """The hook answer's ``available_handoffs``: ``{count, items:[keys]}``; empty when this session has no spare."""
    if not has_spare_allowance([presence]):
        return {"count": 0, "items": []}
    keys = [item.source_key for claim, item, _ in await available_claims(db, [presence.project_id])
            if claim.holder_ref_hash != ref_hash]
    return {"count": len(keys), "items": keys[:20]}


async def handoff_nudges(db: AsyncSession, ref_hash: str, project_id: str) -> list[dict[str, str]]:
    """``[{work_item_key, marker}]`` for this session's live claims whose handoff is missing or behind."""
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
    """``[{work_item_key, marker, kind: "offer"}]``: live claims offered to this agent."""
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
