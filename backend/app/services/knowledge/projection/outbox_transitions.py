"""The closing transitions of an outbox claim: applied, progress, contended. Each answers :data:`LEASE_LOST` instead of
overwriting a newer holder."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EMBED_REVISION,
    OUTBOX_OPERATION_EXTRACT_GRAPH,
    OUTBOX_OPERATION_PARSE_REVISION,
    OUTBOX_OPERATION_PROJECT_REVISION,
    OUTBOX_OPERATION_RETIRE_REVISION,
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_PENDING,
)
from ....time_utils import utc_now
from ..ledger.errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError
from ..ledger.lifecycle import settle_projection
from .outbox_lease import (
    DEFAULT_CONTENTION_DEFER_SECONDS,
    LEASE_LOST,
    MAX_CONTENTION_DEFER_SECONDS,
    ClaimedProjection,
    _owned_transition,
    logger,
)


async def mark_applied(db: AsyncSession, claimed: ClaimedProjection, *, embed_current: bool = False) -> str:
    now = utc_now()
    owned = await _owned_transition(
        db,
        claimed,
        {"state": OUTBOX_STATE_APPLIED, "applied_at": now, "last_failure": None, "claimed_until": None},
    )
    if not owned:
        return LEASE_LOST
    if claimed.operation == OUTBOX_OPERATION_PROJECT_REVISION:
        try:
            await settle_projection(
                db, project_id=claimed.project_id, revision_id=claimed.revision_id, embed=embed_current
            )
        except (EvidenceLedgerContractError, EvidenceRecordNotFoundError):
            # Keep the outbox and revision transition atomic. The caller maps this
            # fixed contract failure and records a bounded failed attempt.
            await db.rollback()
            raise EvidenceLedgerContractError() from None
    elif claimed.operation not in (
        OUTBOX_OPERATION_RETIRE_REVISION,
        OUTBOX_OPERATION_EMBED_REVISION,
        # The parse step added the spans and the projection obligation; this commit carries them.
        OUTBOX_OPERATION_PARSE_REVISION,
        # The extraction step added the last episode's provenance row; this commit carries it.
        OUTBOX_OPERATION_EXTRACT_GRAPH,
    ):
        await db.rollback()
        raise EvidenceLedgerContractError()
    await db.commit()
    return OUTBOX_STATE_APPLIED


async def mark_progress(db: AsyncSession, claimed: ClaimedProjection, projected_through: int) -> str:
    # Partial work is never reported as applied; contention and a bounded batch are not failures.
    if type(claimed) is not ClaimedProjection or type(projected_through) is not int:
        raise EvidenceLedgerContractError()
    if projected_through <= claimed.projected_through_ordinal:
        # The cursor only ever moves forward, so a bug cannot rewind it and make
        # already-projected spans look pending again.
        raise EvidenceLedgerContractError()
    owned = await _owned_transition(
        db,
        claimed,
        {
            "state": OUTBOX_STATE_PENDING,
            "projected_through_ordinal": projected_through,
            "next_attempt_at": utc_now(),
            "claimed_until": None,
            "last_failure": None,
        },
    )
    if not owned:
        return LEASE_LOST
    await db.commit()
    logger.info(
        "Knowledge projection advanced but is not complete: through_ordinal=%d workspace=%s",
        projected_through,
        claimed.project_id,
    )
    return OUTBOX_STATE_PENDING


async def mark_contended(
    db: AsyncSession, claimed: ClaimedProjection, *, retry_after_seconds: int = DEFAULT_CONTENTION_DEFER_SECONDS
) -> str:
    # Due only after a delay, so a worker that lost a race cannot spin; the lease release is lease-conditional.
    if type(claimed) is not ClaimedProjection:
        raise EvidenceLedgerContractError()
    if type(retry_after_seconds) is not int or not 0 < retry_after_seconds <= MAX_CONTENTION_DEFER_SECONDS:
        raise EvidenceLedgerContractError()
    owned = await _owned_transition(
        db,
        claimed,
        {
            "state": OUTBOX_STATE_PENDING,
            "next_attempt_at": utc_now() + timedelta(seconds=retry_after_seconds),
            "claimed_until": None,
        },
    )
    if not owned:
        return LEASE_LOST
    await db.commit()
    logger.info(
        "Knowledge projection deferred while a resource was contended: retry_after_seconds=%d workspace=%s",
        retry_after_seconds,
        claimed.project_id,
    )
    return OUTBOX_STATE_PENDING
