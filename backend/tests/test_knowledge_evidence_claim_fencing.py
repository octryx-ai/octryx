"""Per-claim lease fencing, renewal and contention deferral.

The lease token is the *exact deadline a claim installed*, not the worker identity:
the manual trigger derives one identity per user (``api:<user_id>``), so a stale run
and the run that reclaimed the entry after the stale lease expired routinely share
a ``claimed_by`` value. These tests hold the line that the stale run can transition
nothing, that renewal replaces the claim value instead of mutating it, and that
contention defers an obligation without spending an attempt or another worker's
lease.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select, update

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_CLAIMED,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_UNAVAILABLE,
    REVISION_STATE_REGISTERED,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection import projector as projector_module
from app.services.knowledge.projection.outbox import claim_next, mark_failed, renew_lease
from app.services.knowledge.projection.outbox_lease import DEFAULT_LEASE_SECONDS, LEASE_LOST, ClaimedProjection
from app.services.knowledge.projection.outbox_transitions import mark_applied, mark_contended, mark_progress
from app.services.knowledge.projection.projector import EvidenceProjector
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

PAYLOAD = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"

# The identity two concurrent manual runs of one user really share today.
SHARED_WORKER_ID = "api:u1"

# Every transition that must be fenced by the exact installed deadline. Each entry
# is a coroutine factory so the same stale claim is offered to all of them.
OWNED_TRANSITIONS = {
    "applied": lambda db, claim: mark_applied(db, claim),
    "progress": lambda db, claim: mark_progress(db, claim, claim.projected_through_ordinal + 1),
    "failed": lambda db, claim: mark_failed(db, claim, PROJECTION_FAILURE_UNAVAILABLE),
    "contended": lambda db, claim: mark_contended(db, claim, retry_after_seconds=30),
    "renewed": lambda db, claim: renew_lease(db, claim),
}


def _many_spans(count: int) -> bytes:
    return "\n\n".join(f"Paragraph number {index} about the cluster." for index in range(count)).encode()


async def _prepared(db, *, payload: bytes = PAYLOAD):
    """One Workspace with one committed revision and its pending outbox entry."""
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(
        db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id, require_author=True
    )
    runtime, _, evidence_index = build_runtime()
    ingested = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=payload,
        created_by=None,
    )
    return authorized, runtime, evidence_index, ingested


async def _entry(db, revision_id: str) -> KnowledgeProjectionOutboxEntry:
    return (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry).where(
                KnowledgeProjectionOutboxEntry.revision_id == revision_id
            )
        )
    ).scalar_one()


async def _expire(db, entry_id: str) -> None:
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.id == entry_id)
        .values(claimed_until=utc_now() - timedelta(seconds=1))
    )
    await db.commit()


# --- the stale claim of a shared worker identity ----------------------------


async def test_the_installed_deadline_round_trips_exactly_through_the_database(db):
    """The whole compare-and-set rests on the stored deadline being the exact value."""
    _, _, _, ingested = await _prepared(db)

    claimed = await claim_next(db, worker_id=SHARED_WORKER_ID, lease_seconds=300)

    assert claimed is not None
    entry = await _entry(db, ingested.revision_id)
    assert entry.claimed_until == claimed.lease_until
    # Microsecond-exact, not truncated to whole seconds by the dialect.
    assert entry.claimed_until.microsecond == claimed.lease_until.microsecond


@pytest.mark.parametrize("transition", sorted(OWNED_TRANSITIONS))
async def test_a_stale_claim_cannot_transition_a_reclaim_that_shares_its_worker_id(db, transition):
    """The E5 regression: identical ``claimed_by`` is not identical ownership."""
    _, _, _, ingested = await _prepared(db)
    stale = await claim_next(db, worker_id=SHARED_WORKER_ID, lease_seconds=300)
    assert stale is not None
    await _expire(db, stale.entry_id)
    reclaimed = await claim_next(db, worker_id=SHARED_WORKER_ID, lease_seconds=300)
    assert reclaimed is not None
    assert reclaimed.claimed_by == stale.claimed_by and reclaimed.lease_until != stale.lease_until

    assert await OWNED_TRANSITIONS[transition](db, stale) == LEASE_LOST

    entry = await _entry(db, ingested.revision_id)
    # The active claim is untouched: its lease, attempt budget, failure token and
    # cursor all still belong to the generation that actually owns the entry.
    assert entry.state == OUTBOX_STATE_CLAIMED
    assert entry.claimed_by == SHARED_WORKER_ID
    assert entry.claimed_until == reclaimed.lease_until
    assert entry.attempt_count == 0 and entry.last_failure is None
    assert entry.projected_through_ordinal == 0 and entry.applied_at is None
    revision = await db.get(KnowledgeSourceRevision, ingested.revision_id)
    assert revision is not None and revision.state == REVISION_STATE_REGISTERED


# --- renewal replaces the claim value ---------------------------------------


async def test_renewal_advances_the_deadline_and_retires_the_previous_claim_value(db):
    _, _, _, ingested = await _prepared(db)
    claimed = await claim_next(db, worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    renewed = await renew_lease(db, claimed, lease_seconds=DEFAULT_LEASE_SECONDS)

    assert type(renewed) is ClaimedProjection
    assert renewed.lease_until > claimed.lease_until
    assert (renewed.entry_id, renewed.claimed_by, renewed.attempt_count) == (
        claimed.entry_id,
        claimed.claimed_by,
        claimed.attempt_count,
    )
    assert (await _entry(db, ingested.revision_id)).claimed_until == renewed.lease_until
    # The superseded value is refused even though its worker still holds the lease.
    assert await mark_failed(db, claimed, PROJECTION_FAILURE_UNAVAILABLE) == LEASE_LOST
    assert (await _entry(db, ingested.revision_id)).attempt_count == 0
    # The newest value is the one that works.
    assert await mark_applied(db, renewed) == OUTBOX_STATE_APPLIED


async def test_an_expired_lease_cannot_be_renewed_back_to_life(db):
    _, _, _, ingested = await _prepared(db)
    claimed = await claim_next(db, worker_id="worker-a", lease_seconds=300)
    assert claimed is not None
    await _expire(db, claimed.entry_id)
    expired_until = (await _entry(db, ingested.revision_id)).claimed_until

    assert await renew_lease(db, claimed) == LEASE_LOST

    assert (await _entry(db, ingested.revision_id)).claimed_until == expired_until


# --- contention defers, it does not fail ------------------------------------


async def test_contention_returns_the_entry_to_pending_without_consuming_an_attempt(db):
    _, _, _, ingested = await _prepared(db)
    first = await claim_next(db, worker_id="worker-a", lease_seconds=300)
    assert first is not None
    assert await mark_failed(db, first, PROJECTION_FAILURE_UNAVAILABLE) == OUTBOX_STATE_PENDING
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.id == first.entry_id)
        .values(next_attempt_at=utc_now() - timedelta(seconds=1))
    )
    await db.commit()
    claimed = await claim_next(db, worker_id="worker-b", lease_seconds=300)
    assert claimed is not None and claimed.attempt_count == 1

    assert await mark_contended(db, claimed, retry_after_seconds=30) == OUTBOX_STATE_PENDING

    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING and entry.claimed_until is None
    # Contention is not an attempt, and it invents no failure token of its own.
    assert entry.attempt_count == 1 and entry.last_failure == PROJECTION_FAILURE_UNAVAILABLE
    assert entry.next_attempt_at > utc_now()
    # Bounded, not a hot loop: the entry is not due again immediately.
    assert await claim_next(db, worker_id="worker-b") is None


async def test_contention_cannot_release_another_owners_lease(db):
    _, _, _, ingested = await _prepared(db)
    stale = await claim_next(db, worker_id="worker-a", lease_seconds=300)
    assert stale is not None
    await _expire(db, stale.entry_id)
    reclaimed = await claim_next(db, worker_id="worker-b", lease_seconds=300)
    assert reclaimed is not None

    assert await mark_contended(db, stale, retry_after_seconds=30) == LEASE_LOST

    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_CLAIMED and entry.claimed_by == "worker-b"
    assert entry.claimed_until == reclaimed.lease_until


# --- renewal inside a bounded multi-span run --------------------------------


async def test_a_bounded_run_renews_its_claim_instead_of_racing_the_run_budget(db):
    """The closing transition only succeeds with the token renewal handed back."""
    authorized, runtime, evidence_index, ingested = await _prepared(db, payload=_many_spans(5))
    projector = EvidenceProjector(runtime)
    renewals: list[str] = []
    real_renew = projector_module.renew_lease

    async def counting_renew(db_, claim, **kwargs):
        renewals.append(claim.entry_id)
        return await real_renew(db_, claim, **kwargs)

    # A lease at the renewal margin: the first span of each run crosses it once,
    # and renewal installs a full lease again, so no further renewal follows.
    with (
        patch.object(projector_module, "MAX_SPANS_PER_RUN", 3),
        patch.object(projector_module, "renew_lease", counting_renew),
    ):
        claimed = await claim_next(
            db, worker_id="worker-a", lease_seconds=projector_module.LEASE_RENEWAL_MARGIN_SECONDS
        )
        assert claimed is not None
        first = await projector.apply_claimed(db, claimed)
        assert (first.spans_projected, first.more_spans_pending, first.applied) == (3, True, False)
        assert first.outbox_state == OUTBOX_STATE_PENDING

        second_claim = await claim_next(
            db, worker_id="worker-a", lease_seconds=projector_module.LEASE_RENEWAL_MARGIN_SECONDS
        )
        assert second_claim is not None
        second = await projector.apply_claimed(db, second_claim)

    assert (second.spans_projected, second.more_spans_pending, second.applied) == (2, False, True)
    assert renewals == [claimed.entry_id, claimed.entry_id]
    assert len(evidence_index.evidence_keys(authorized.workspace.canonical)) == ingested.span_count == 5
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED


async def test_a_refused_renewal_stops_the_run_before_it_projects_anything(db):
    authorized, runtime, evidence_index, ingested = await _prepared(db)
    projector = EvidenceProjector(runtime)

    async def refused_renew(*_args, **_kwargs):
        return LEASE_LOST

    with patch.object(projector_module, "renew_lease", refused_renew):
        claimed = await claim_next(
            db, worker_id="worker-a", lease_seconds=projector_module.LEASE_RENEWAL_MARGIN_SECONDS
        )
        assert claimed is not None
        outcome = await projector.apply_claimed(db, claimed)

    assert outcome.outbox_state == LEASE_LOST
    assert outcome.applied is False and outcome.failure is None and outcome.spans_projected == 0
    assert not evidence_index.evidence_keys(authorized.workspace.canonical)
    entry = await _entry(db, ingested.revision_id)
    # No transition was attempted at all: the run touched nothing it no longer owns.
    assert entry.state == OUTBOX_STATE_CLAIMED and entry.claimed_until == claimed.lease_until
    assert entry.attempt_count == 0 and entry.last_failure is None
