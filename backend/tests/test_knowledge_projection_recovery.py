"""Governed projection retry and requeue with audit.

Proves the four things the recovery boundary claims: only Workspace authors reach it
and everyone else gets the established indistinguishable refusals; every transition is
compare-and-set, so ``claimed``/``applied`` survive and repeats are deterministic; the
state change and exactly one redacted audit record commit together or not at all; and
the identical-upload recovery now runs through this one service, so no second reset
rule remains anywhere in the package.
"""

from __future__ import annotations

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_CLAIMED,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_UNAVAILABLE,
)
from app.services.knowledge.projection import recovery, recovery_vocabulary
from app.services.knowledge.projection.outbox import claim_next
from app.services.knowledge.projection.outbox_transitions import mark_applied
from app.time_utils import utc_now
from tests.knowledge_projection_recovery_support import (  # noqa: F401
    _audit_records,
    _dead_lettered,
    _entry,
    _force,
    _recover,
    _release_evidence_runtime,
    _url,
    as_user,
)

# --- compare-and-set, concurrency, idempotency -------------------------------


async def test_requeue_moves_a_dead_letter_to_pending_and_preserves_the_cursor(db):
    _, user, authorized, _, _, ingested = await _dead_lettered(db)
    await _force(db, ingested.revision_id, projected_through_ordinal=1)

    result = await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)

    assert result.result == recovery.RECOVERY_RESULT_REQUEUED and result.changed is True
    assert result.previous_state == OUTBOX_STATE_DEAD_LETTER
    assert result.outbox_state == OUTBOX_STATE_PENDING
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING
    assert entry.attempt_count == 0 and entry.last_failure is None
    assert entry.claimed_by is None and entry.claimed_at is None and entry.claimed_until is None
    assert entry.next_attempt_at <= utc_now()
    # Already-projected spans are not re-projected: the cursor survives recovery.
    assert entry.projected_through_ordinal == 1


async def test_a_repeated_requeue_is_idempotent_and_writes_one_record(db):
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)

    first = await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)
    second = await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)

    assert first.result == recovery.RECOVERY_RESULT_REQUEUED
    assert second.result == recovery_vocabulary.RECOVERY_RESULT_ALREADY_PENDING
    assert second.changed is False and second.outbox_state == OUTBOX_STATE_PENDING
    assert len(await _audit_records(db, workspace_id)) == 1


async def test_recovery_refuses_a_live_claim_and_leaves_the_lease_intact(client, db, as_user):  # noqa: F811
    workspace_id, user, _, _, _, ingested = await _dead_lettered(db)
    # Only a due entry is claimable, so the obligation is made claimable first.
    await _force(db, ingested.revision_id, state=OUTBOX_STATE_PENDING, next_attempt_at=utc_now())
    claimed = await claim_next(db, worker_id="worker-a", project_id=workspace_id)
    assert claimed is not None

    as_user(user)
    for suffix in ("requeue", "retry-now"):
        assert (await client.post(_url(workspace_id, ingested.revision_id, suffix))).status_code == 409

    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_CLAIMED
    assert entry.claimed_by == "worker-a" and entry.claimed_until == claimed.lease_until
    # The holder's own fenced transition still succeeds: the lease was never touched.
    assert await mark_applied(db, claimed) == OUTBOX_STATE_APPLIED
    assert await _audit_records(db, workspace_id) == []


async def test_recovery_refuses_an_applied_obligation(client, db, as_user):  # noqa: F811
    workspace_id, user, _, _, _, ingested = await _dead_lettered(db)
    await _force(db, ingested.revision_id, state=OUTBOX_STATE_APPLIED, applied_at=utc_now())

    as_user(user)
    for suffix in ("requeue", "retry-now"):
        assert (await client.post(_url(workspace_id, ingested.revision_id, suffix))).status_code == 409
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED
    assert await _audit_records(db, workspace_id) == []


async def test_a_stale_read_loses_the_compare_and_set_without_mutating(db, monkeypatch):
    """The race window: a second request whose read still saw ``dead_letter``."""
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)
    entry_id = (await _entry(db, ingested.revision_id)).id

    await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)
    await _force(db, ingested.revision_id, attempt_count=3, last_failure=PROJECTION_FAILURE_UNAVAILABLE)

    real_load = recovery._load
    stale = [
        recovery._Obligation(
            entry_id=entry_id,
            state=OUTBOX_STATE_DEAD_LETTER,
            next_attempt_at=utc_now(),
            due=True,
        )
    ]

    async def stale_once(*args, **kwargs):
        return stale.pop() if stale else await real_load(*args, **kwargs)

    monkeypatch.setattr(recovery, "_load", stale_once)
    late = await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)

    # The compare-and-set found ``pending``, not the ``dead_letter`` it was told.
    assert late.result == recovery_vocabulary.RECOVERY_RESULT_ALREADY_PENDING and late.changed is False
    entry = await _entry(db, ingested.revision_id)
    assert entry.attempt_count == 3 and entry.last_failure == PROJECTION_FAILURE_UNAVAILABLE
    assert len(await _audit_records(db, workspace_id)) == 1
