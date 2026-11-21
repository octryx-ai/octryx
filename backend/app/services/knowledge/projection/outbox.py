"""Transactional-outbox claim, retry, and dead-letter transitions.

No fire-and-forget. A committed revision leaves exactly one ``pending`` entry; a
projector claims it with a **bounded lease**, applies it idempotently, and marks
it ``applied``. A failure records a *fixed failure token* (never a server
message), increments the attempt count, and schedules the next attempt; once the
bounded maximum is reached the entry becomes ``dead_letter`` and is never retried.

Claiming is a conditional ``UPDATE`` whose ``WHERE`` still contains the state the
row was read in, and the claim only counts when it changed exactly one row. That
works on PostgreSQL and SQLite alike without ``SELECT ... FOR UPDATE``, so two
projectors cannot hold the same entry: the loser sees ``rowcount == 0`` and moves on.

An expired lease is reclaimable, which is why a projector that crashed
mid-application does not strand its entry — and that is exactly why **every**
transition out of a claim is conditional on still owning it.

The ownership token is the *exact lease deadline this claim installed*, not the
worker identity: ``claimed_by`` alone is not a generation counter, and the manual
trigger derives one identity per user (``api:<user_id>``), so two claims of the
same entry routinely carry the same worker id. Every owned transition therefore
compares entry id, ``state == 'claimed'``, ``claimed_by``, ``claimed_until ==
ClaimedProjection.lease_until`` and a still-live deadline, and checks ``rowcount``.
A worker whose lease expired — whether it was reclaimed by another identity, by the
same identity, or not yet reclaimed at all — reports :data:`LEASE_LOST` instead of
overwriting the new holder's attempt count, its failure token, its lease, or its
cursor. Losing a lease is not an error of the projection: the spans were written
idempotently, the new holder owns the outcome.

Because the deadline *is* the token, :func:`renew_lease` returns a **new**
``ClaimedProjection`` carrying the advanced deadline and invalidates the previous
one; a long bounded run keeps its claim alive instead of relying on an unwritten
"the run budget is shorter than the lease" coupling between two modules.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    ALL_OUTBOX_OPERATIONS,
    ALL_PROJECTION_FAILURES,
    OUTBOX_STATE_CLAIMED,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    KnowledgeProjectionOutboxEntry,
)
from ....time_utils import utc_now
from ..ledger.errors import EvidenceLedgerContractError
from .outbox_lease import (
    DEFAULT_LEASE_SECONDS,
    LEASE_LOST,
    MAX_CLAIMED_BY_CHARS,
    MAX_LEASE_SECONDS,
    ClaimedProjection,
    _backoff_seconds,
    _owned_transition,
    logger,
)


async def claim_next(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    project_id: str | None = None,
) -> ClaimedProjection | None:
    """Lease the next due entry, or return ``None`` when nothing is due."""
    if type(worker_id) is not str or not 0 < len(worker_id) <= MAX_CLAIMED_BY_CHARS:
        raise EvidenceLedgerContractError()
    if type(lease_seconds) is not int or not 0 < lease_seconds <= MAX_LEASE_SECONDS:
        raise EvidenceLedgerContractError()
    now = utc_now()
    statement = (
        select(
            KnowledgeProjectionOutboxEntry.id,
            KnowledgeProjectionOutboxEntry.project_id,
            KnowledgeProjectionOutboxEntry.revision_id,
            KnowledgeProjectionOutboxEntry.operation,
            KnowledgeProjectionOutboxEntry.state,
            KnowledgeProjectionOutboxEntry.attempt_count,
            KnowledgeProjectionOutboxEntry.max_attempts,
            KnowledgeProjectionOutboxEntry.projected_through_ordinal,
            KnowledgeProjectionOutboxEntry.claimed_by,
            KnowledgeProjectionOutboxEntry.claimed_until,
        )
        .where(
            KnowledgeProjectionOutboxEntry.operation.in_(ALL_OUTBOX_OPERATIONS),
            KnowledgeProjectionOutboxEntry.next_attempt_at <= now,
            or_(
                KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_PENDING,
                # An expired lease is reclaimable: a crashed projector must not
                # strand the entry it was holding.
                (KnowledgeProjectionOutboxEntry.state == OUTBOX_STATE_CLAIMED)
                & (KnowledgeProjectionOutboxEntry.claimed_until <= now),
            ),
        )
        .order_by(KnowledgeProjectionOutboxEntry.next_attempt_at)
        .limit(8)
    )
    if project_id is not None:
        statement = statement.where(KnowledgeProjectionOutboxEntry.project_id == project_id)

    for row in (await db.execute(statement)).all():
        claimed = await _claim(db, row, worker_id=worker_id, lease_seconds=lease_seconds, now=now)
        if claimed is not None:
            return claimed
    return None


async def _claim(
    db: AsyncSession, row: object, *, worker_id: str, lease_seconds: int, now: object
) -> ClaimedProjection | None:
    (
        entry_id,
        project_id,
        revision_id,
        operation,
        previous_state,
        attempt_count,
        max_attempts,
        projected_through,
        previous_claimed_by,
        previous_claimed_until,
    ) = tuple(row)  # type: ignore[misc]
    ownership_conditions = []
    if previous_state == OUTBOX_STATE_CLAIMED:
        # A reclaimed row remains in ``claimed`` state. State alone is therefore
        # not a compare-and-swap token: two workers that both observed the same
        # expired claim could otherwise overwrite each other in sequence.
        ownership_conditions.extend(
            (
                KnowledgeProjectionOutboxEntry.claimed_by == previous_claimed_by,
                KnowledgeProjectionOutboxEntry.claimed_until == previous_claimed_until,
                KnowledgeProjectionOutboxEntry.claimed_until <= now,
            )
        )
    lease_until = now + timedelta(seconds=lease_seconds)
    result = await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(
            KnowledgeProjectionOutboxEntry.id == entry_id,
            # Still the state we read: a concurrent claim invalidates this update.
            KnowledgeProjectionOutboxEntry.state == previous_state,
            *ownership_conditions,
        )
        .values(
            state=OUTBOX_STATE_CLAIMED,
            claimed_by=worker_id,
            claimed_at=now,
            claimed_until=lease_until,
        )
    )
    await db.commit()
    if result.rowcount != 1:
        return None
    return ClaimedProjection(
        entry_id=entry_id,
        project_id=project_id,
        revision_id=revision_id,
        operation=operation,
        attempt_count=int(attempt_count),
        max_attempts=int(max_attempts),
        claimed_by=worker_id,
        projected_through_ordinal=int(projected_through or 0),
        # The installed deadline is handed back verbatim: it is the token every
        # later transition of *this* claim generation is compared against.
        lease_until=lease_until,
    )


async def renew_lease(
    db: AsyncSession, claimed: ClaimedProjection, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> ClaimedProjection | str:
    """Extend a still-owned claim and answer the claim value that replaces it.

    Returns a new :class:`ClaimedProjection` whose ``lease_until`` is the advanced
    deadline, or :data:`LEASE_LOST` when this claim generation no longer owns the
    row. The previous value is stale from here on: its deadline is no longer the one
    stored, so every transition made with it is refused. Callers must keep the
    returned value, which is what makes a long bounded run explicit instead of
    silently racing its own lease.
    """
    if type(claimed) is not ClaimedProjection:
        raise EvidenceLedgerContractError()
    if type(lease_seconds) is not int or not 0 < lease_seconds <= MAX_LEASE_SECONDS:
        raise EvidenceLedgerContractError()
    renewed_until = utc_now() + timedelta(seconds=lease_seconds)
    owned = await _owned_transition(db, claimed, {"claimed_until": renewed_until})
    if not owned:
        return LEASE_LOST
    await db.commit()
    return replace(claimed, lease_until=renewed_until)



async def mark_failed(db: AsyncSession, claimed: ClaimedProjection, failure: str) -> str:
    """Record a fixed failure token and schedule or dead-letter the entry."""
    if type(claimed) is not ClaimedProjection:
        raise EvidenceLedgerContractError()
    if failure not in ALL_PROJECTION_FAILURES:
        # Only the fixed tokens are persistable, so no server text can be stored.
        raise EvidenceLedgerContractError()
    attempts = claimed.attempt_count + 1
    exhausted = attempts >= claimed.max_attempts
    state = OUTBOX_STATE_DEAD_LETTER if exhausted else OUTBOX_STATE_PENDING
    next_attempt_at = utc_now() + timedelta(seconds=_backoff_seconds(attempts))
    owned = await _owned_transition(
        db,
        claimed,
        {
            "state": state,
            "attempt_count": attempts,
            "last_failure": failure,
            "next_attempt_at": next_attempt_at,
            "claimed_until": None,
        },
    )
    if not owned:
        return LEASE_LOST
    await db.commit()
    logger.warning(
        "Knowledge projection attempt failed: state=%s failure=%s attempts=%d workspace=%s",
        state,
        failure,
        attempts,
        claimed.project_id,
    )
    return state


__all__ = [
    "claim_next",
    "mark_failed",
    "renew_lease",
]
