"""Retry-now pulls scheduled attempts forward, allows exactly one overlapping mutation and leaves requeue explicit and claimable."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.project.knowledge_evidence import OUTBOX_STATE_APPLIED, OUTBOX_STATE_DEAD_LETTER, OUTBOX_STATE_PENDING
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError
from app.services.knowledge.projection import recovery, recovery_vocabulary
from app.time_utils import utc_now
from tests.knowledge_projection_recovery_support import (  # noqa: F401
    BASE,
    _audit_records,
    _dead_lettered,
    _drop_obligation,
    _entry,
    _force,
    _ingested,
    _recover,
    _release_evidence_runtime,
    _url,
    as_user,
)


async def test_retry_now_pulls_a_scheduled_attempt_forward_without_spending_the_budget(
    client, db, as_user  # noqa: F811
):
    workspace_id, user, _, _, _, ingested = await _dead_lettered(db)
    await _force(
        db,
        ingested.revision_id,
        state=OUTBOX_STATE_PENDING,
        attempt_count=2,
        next_attempt_at=utc_now() + timedelta(hours=1),
    )

    as_user(user)
    url = _url(workspace_id, ingested.revision_id, "retry-now")
    first = await client.post(url)
    second = await client.post(url)

    assert first.status_code == 200
    assert first.json()["result"] == recovery.RECOVERY_RESULT_RETRY_SCHEDULED
    assert first.json()["recovered"] is True
    assert second.status_code == 200
    assert second.json()["result"] == recovery_vocabulary.RECOVERY_RESULT_ALREADY_DUE
    assert second.json()["recovered"] is False
    entry = await _entry(db, ingested.revision_id)
    assert entry.next_attempt_at <= utc_now()
    # Pulling an attempt forward must not widen the bounded retry budget.
    assert entry.attempt_count == 2
    assert len(await _audit_records(db, workspace_id)) == 1


async def test_inverse_retry_now_overlap_allows_exactly_one_mutation_and_audit(db, monkeypatch):
    """The later request wins first; the earlier stale request must still lose.

    Matching only ``next_attempt_at > request_now`` is insufficient here: after the
    later request writes its later clock value, that value is still greater than the
    earlier request's clock and both updates would succeed. The exact loaded schedule
    value is the CAS generation token that makes the second update a no-op.
    """
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)
    scheduled = utc_now() + timedelta(hours=1)
    await _force(
        db,
        ingested.revision_id,
        state=OUTBOX_STATE_PENDING,
        attempt_count=2,
        next_attempt_at=scheduled,
    )
    entry = await _entry(db, ingested.revision_id)
    snapshot = recovery._Obligation(
        entry_id=entry.id,
        state=OUTBOX_STATE_PENDING,
        next_attempt_at=entry.next_attempt_at,
        due=False,
    )

    # Both requests have already read the original schedule. Request B has the
    # later clock but reaches UPDATE/commit first; stale A resumes afterwards.
    earlier_request_now = scheduled - timedelta(minutes=30)
    later_request_now = earlier_request_now + timedelta(seconds=1)
    classify_after_winner = later_request_now + timedelta(microseconds=1)
    request_times = iter((later_request_now, earlier_request_now, classify_after_winner))
    stale_reads = [snapshot, snapshot]
    real_load = recovery._load

    async def two_stale_reads_then_reality(*args, **kwargs):
        if stale_reads:
            return stale_reads.pop(0)
        return await real_load(*args, **kwargs)

    monkeypatch.setattr(recovery, "utc_now", lambda: next(request_times))
    monkeypatch.setattr(recovery, "_load", two_stale_reads_then_reality)

    later = await _recover(
        db,
        authorized,
        ingested.revision_id,
        operation=recovery_vocabulary.RECOVERY_OPERATION_RETRY_NOW,
        actor_user_id=user.id,
    )
    earlier = await _recover(
        db,
        authorized,
        ingested.revision_id,
        operation=recovery_vocabulary.RECOVERY_OPERATION_RETRY_NOW,
        actor_user_id=user.id,
    )

    assert later.result == recovery.RECOVERY_RESULT_RETRY_SCHEDULED and later.changed is True
    assert earlier.result == recovery_vocabulary.RECOVERY_RESULT_ALREADY_DUE and earlier.changed is False
    entry = await _entry(db, ingested.revision_id)
    assert entry.next_attempt_at == later_request_now and entry.attempt_count == 2
    assert len(await _audit_records(db, workspace_id)) == 1


async def test_retry_now_refuses_a_dead_letter_so_requeue_stays_explicit(client, db, as_user):  # noqa: F811
    workspace_id, user, _, _, _, ingested = await _dead_lettered(db)
    as_user(user)

    assert (await client.post(_url(workspace_id, ingested.revision_id, "retry-now"))).status_code == 409
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER


async def test_a_requeued_obligation_is_claimable_by_the_manual_projection_again(client, db, as_user):  # noqa: F811
    """Recovery is real work, not a state cosmetic: the manual run drains it."""
    workspace_id, user, authorized, _, evidence_index, ingested = await _dead_lettered(db)
    as_user(user)

    assert (await client.post(_url(workspace_id, ingested.revision_id, "requeue"))).status_code == 200

    run = await client.post(f"{BASE}/{workspace_id}/knowledge/projection/run")

    assert run.status_code == 200
    assert run.json()["claimed"] is True and run.json()["applied"] is True
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_APPLIED
    assert len(evidence_index.evidence_keys(authorized.workspace.canonical)) == 2


async def test_an_unknown_operation_token_is_a_contract_violation(db):
    _, user, authorized, _, _, ingested = await _dead_lettered(db)

    with pytest.raises(EvidenceLedgerContractError):
        await _recover(db, authorized, ingested.revision_id, operation="reset_everything", actor_user_id=user.id)
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_DEAD_LETTER


async def test_a_missing_obligation_is_not_found_for_an_explicit_recovery_request(db):
    _, user, authorized, _, _, ingested = await _ingested(db)
    await _drop_obligation(db, ingested.revision_id)

    with pytest.raises(EvidenceRecordNotFoundError):
        await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)
