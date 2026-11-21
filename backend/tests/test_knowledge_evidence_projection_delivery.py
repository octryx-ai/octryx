"""Outbox projection delivery: exactly once, convergence on re-apply, bounded cursors, bounded retries ending in dead-letter, requeue on re-upload, and lease ownership."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import update

from app.models.project.knowledge_evidence import (
    DEFAULT_MAX_PROJECTION_ATTEMPTS,
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_CLAIMED,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_UNAVAILABLE,
    REVISION_STATE_REGISTERED,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection import projector as projector_module
from app.services.knowledge.projection.outbox import claim_next, mark_failed
from app.services.knowledge.projection.outbox_lease import LEASE_LOST
from app.services.knowledge.projection.projector import EvidenceProjector
from app.time_utils import utc_now
from tests.knowledge_evidence_index_support import FakeEvidenceIndex
from tests.knowledge_evidence_projection_support import PAYLOAD, _entry, _prepared


def _many_spans(count: int) -> bytes:
    """A payload that splits into exactly ``count`` paragraph spans."""
    return "\n\n".join(f"Paragraph number {index} about the cluster." for index in range(count)).encode()


async def _make_due(db, revision_id: str) -> None:
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.revision_id == revision_id)
        .values(next_attempt_at=utc_now() - timedelta(seconds=1))
    )
    await db.commit()


# --- exactly once and convergence -------------------------------------------


async def test_a_pending_obligation_is_applied_exactly_once_later(db):
    evidence_index = FakeEvidenceIndex(unavailable=True)
    authorized, runtime, _, evidence_index, ingested = await _prepared(db, index=evidence_index)
    projector = EvidenceProjector(runtime)

    failed = await projector.project_once(db, worker_id="worker-a")
    assert failed is not None and failed.applied is False

    evidence_index.unavailable = False
    await _make_due(db, ingested.revision_id)

    applied = await projector.project_once(db, worker_id="worker-a")
    assert applied is not None and applied.applied is True
    database = authorized.workspace.canonical
    assert len(evidence_index.evidence_keys(database)) == ingested.span_count

    # Nothing is due any more: the obligation is not applied twice.
    assert await projector.project_once(db, worker_id="worker-a") is None
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED


async def test_reapplying_a_claimed_entry_converges_instead_of_duplicating(db):
    """The upsert converges, and a claim that is no longer held reports lease loss.

    A duplicate delivery of the same lease must not produce a second set of records
    *and* must not be reported as a fresh successful application: the entry is
    already ``applied``, so this worker does not own it.
    """
    authorized, runtime, _, evidence_index, ingested = await _prepared(db)
    projector = EvidenceProjector(runtime)
    database = authorized.workspace.canonical

    claimed = await claim_next(db, worker_id="worker-a")
    assert claimed is not None
    first = await projector.apply_claimed(db, claimed)
    assert first.applied is True
    keys_after_first = evidence_index.evidence_keys(database)

    repeated = await projector.apply_claimed(db, claimed)

    assert repeated.outbox_state == LEASE_LOST
    assert repeated.applied is False and repeated.failure is None
    assert evidence_index.evidence_keys(database) == keys_after_first
    assert len(keys_after_first) == ingested.span_count
    # The entry stays applied: the duplicate delivery changed no ledger state.
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED


async def test_a_bounded_run_advances_a_cursor_instead_of_projecting_everything(db):
    """Finding 10: a revision larger than the per-run bound needs repeated runs."""
    authorized, runtime, _, evidence_index, ingested = await _prepared(db, payload=_many_spans(7))
    projector = EvidenceProjector(runtime)
    database = authorized.workspace.canonical

    with patch.object(projector_module, "MAX_SPANS_PER_RUN", 3):
        first = await projector.project_once(db, worker_id="worker-a")
        assert first is not None
        assert (first.spans_projected, first.more_spans_pending, first.applied) == (3, True, False)
        assert first.outbox_state == OUTBOX_STATE_PENDING
        assert len(evidence_index.evidence_keys(database)) == 3
        # The revision is not projected while work is still owed.
        assert (await db.get(KnowledgeSourceRevision, ingested.revision_id)).state == REVISION_STATE_REGISTERED

        second = await projector.project_once(db, worker_id="worker-a")
        assert second is not None and second.more_spans_pending is True
        assert second.spans_projected == 3

        third = await projector.project_once(db, worker_id="worker-a")
        assert third is not None
        assert (third.spans_projected, third.more_spans_pending, third.applied) == (1, False, True)

    assert len(evidence_index.evidence_keys(database)) == ingested.span_count == 7
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED
    assert await projector.project_once(db, worker_id="worker-a") is None


# --- bounded retry and dead-letter ------------------------------------------


async def test_retries_are_bounded_and_end_in_dead_letter(db):
    _, runtime, _, _, ingested = await _prepared(db, index=FakeEvidenceIndex(unavailable=True))
    projector = EvidenceProjector(runtime)

    states = []
    for _ in range(DEFAULT_MAX_PROJECTION_ATTEMPTS):
        await _make_due(db, ingested.revision_id)
        outcome = await projector.project_once(db, worker_id="worker-a")
        assert outcome is not None
        states.append(outcome.outbox_state)

    assert states[:-1] == [OUTBOX_STATE_PENDING] * (DEFAULT_MAX_PROJECTION_ATTEMPTS - 1)
    assert states[-1] == OUTBOX_STATE_DEAD_LETTER
    entry = await _entry(db, ingested.revision_id)
    assert entry.attempt_count == DEFAULT_MAX_PROJECTION_ATTEMPTS
    # Terminal: a dead-lettered entry is never claimed again.
    await _make_due(db, ingested.revision_id)
    assert await projector.project_once(db, worker_id="worker-a") is None


async def test_reuploading_the_same_revision_requeues_its_dead_letter(db):
    """A user has a governed recovery path; terminal does not mean manual SQL."""
    authorized, runtime, _, _, ingested = await _prepared(db, index=FakeEvidenceIndex(unavailable=True))
    projector = EvidenceProjector(runtime)
    for _ in range(DEFAULT_MAX_PROJECTION_ATTEMPTS):
        await _make_due(db, ingested.revision_id)
        assert await projector.project_once(db, worker_id="worker-a") is not None
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER

    repeated = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=PAYLOAD,
        created_by=None,
    )

    assert repeated.created is False and repeated.revision_id == ingested.revision_id
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING
    assert entry.attempt_count == 0 and entry.last_failure is None


async def test_a_live_lease_blocks_a_second_projector_and_an_expired_one_does_not(db):
    _, runtime, _, _, ingested = await _prepared(db)

    first = await claim_next(db, worker_id="worker-a", lease_seconds=300)
    assert first is not None
    assert await claim_next(db, worker_id="worker-b") is None
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_CLAIMED

    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.id == first.entry_id)
        .values(claimed_until=utc_now() - timedelta(seconds=1))
    )
    await db.commit()

    reclaimed = await claim_next(db, worker_id="worker-b")
    assert reclaimed is not None and reclaimed.entry_id == first.entry_id
    assert await mark_failed(db, first, PROJECTION_FAILURE_UNAVAILABLE) == LEASE_LOST
    entry = await _entry(db, ingested.revision_id)
    assert entry.claimed_by == "worker-b" and entry.attempt_count == 0


async def test_an_expired_unreclaimed_lease_cannot_transition_the_entry(db):
    """Expiry itself ends ownership, even before another worker reclaims the row."""
    _, _, _, _, ingested = await _prepared(db)
    claimed = await claim_next(db, worker_id="worker-a", lease_seconds=300)
    assert claimed is not None
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.id == claimed.entry_id)
        .values(claimed_until=utc_now() - timedelta(seconds=1))
    )
    await db.commit()

    assert await mark_failed(db, claimed, PROJECTION_FAILURE_UNAVAILABLE) == LEASE_LOST
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_CLAIMED
    assert entry.attempt_count == 0 and entry.last_failure is None


async def test_claiming_is_scoped_to_one_workspace_when_asked(db):
    _, runtime_a, _, _, first = await _prepared(db)
    authorized_b, _, _, _, second = await _prepared(db)

    claimed = await claim_next(db, worker_id="worker-a", project_id=authorized_b.project_id)

    assert claimed is not None
    assert claimed.revision_id == second.revision_id
    assert claimed.project_id == authorized_b.project_id
