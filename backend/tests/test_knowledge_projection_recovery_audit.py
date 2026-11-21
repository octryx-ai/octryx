"""Recovery transitions and their redacted audit records commit or roll back together."""

from __future__ import annotations

import pytest

from app.models.project.knowledge_evidence import (
    DEFAULT_MAX_PROJECTION_ATTEMPTS,
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_UNAVAILABLE,
)
from app.models.security.compliance_audit import ALL_AUDIT_EVENT_TYPES, AUDIT_RUNTIME_ACTION, OUTCOME_ALLOWED
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError
from app.services.knowledge.projection import recovery
from app.services.request_context import reset_current_request_id, set_current_request_id
from tests.knowledge_evidence_seed_support import new_workspace_id
from tests.knowledge_projection_recovery_support import (  # noqa: F401
    REQUEUE,
    _audit_records,
    _dead_lettered,
    _entry,
    _recover,
    _release_evidence_runtime,
)

# --- atomicity and audit content --------------------------------------------


async def test_the_transition_and_its_audit_record_commit_in_one_transaction(db):
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)
    commits: list[int] = []
    real_commit = db.commit

    async def counted_commit():
        commits.append(1)
        await real_commit()

    db.commit = counted_commit
    try:
        await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)
    finally:
        db.commit = real_commit

    # One commit, both rows: the record cannot be observed without the transition.
    assert len(commits) == 1
    assert (await _entry(db, ingested.revision_id)).state == OUTBOX_STATE_PENDING
    assert len(await _audit_records(db, workspace_id)) == 1


async def test_a_failing_audit_record_rolls_the_recovery_back(db, monkeypatch):
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)

    async def refuse(*args, **kwargs):
        raise RuntimeError("audit store refused")

    monkeypatch.setattr(recovery, "create_audit_record", refuse)
    with pytest.raises(RuntimeError):
        await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)

    # The service rolled back: no unaudited transition of durable delivery state.
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_DEAD_LETTER
    assert entry.attempt_count == DEFAULT_MAX_PROJECTION_ATTEMPTS
    assert entry.last_failure == PROJECTION_FAILURE_UNAVAILABLE
    assert await _audit_records(db, workspace_id) == []


async def test_the_audit_record_carries_only_actor_workspace_transition_and_correlation(db):
    workspace_id, user, authorized, _, _, ingested = await _dead_lettered(db)
    entry_id = (await _entry(db, ingested.revision_id)).id

    token = set_current_request_id("req-848-correlation")
    try:
        await _recover(db, authorized, ingested.revision_id, actor_user_id=user.id)
    finally:
        reset_current_request_id(token)

    record = (await _audit_records(db, workspace_id))[0]
    assert AUDIT_RUNTIME_ACTION in ALL_AUDIT_EVENT_TYPES
    assert record.event_type == AUDIT_RUNTIME_ACTION and record.outcome == OUTCOME_ALLOWED
    assert record.resource_type == recovery.AUDIT_RESOURCE_TYPE
    assert record.resource_id == entry_id and record.resource_name is None
    assert record.actor_user_id == user.id and record.actor_role == authorized.role
    assert record.project_id == workspace_id
    assert record.request_id == "req-848-correlation"
    assert record.details == {
        "operation": REQUEUE,
        "outbox_entry_id": entry_id,
        "revision_id": ingested.revision_id,
        "previous_state": OUTBOX_STATE_DEAD_LETTER,
        "result": recovery.RECOVERY_RESULT_REQUEUED,
    }
    assert record.contains_sensitive is False and record.redacted_fields == []
    # No document content, storage topology, or dependency text is persistable here.
    rendered = f"{record.details}{record.resource_name}{record.classification_level}"
    for forbidden in ("Zurich", "Runbook", "runbook", "octryx-knowledge-test", "octryx_ws_", "sha256/"):
        assert forbidden not in rendered


async def test_a_free_text_audit_value_is_refused_before_the_insert(db):
    """The audited values are bounded in Python, not only by the column width."""
    free_text_id = recovery.ProjectionRecovery(
        entry_id="not a uuid but free text",
        revision_id=new_workspace_id(),
        operation=REQUEUE,
        previous_state=OUTBOX_STATE_DEAD_LETTER,
        result=recovery.RECOVERY_RESULT_REQUEUED,
        outbox_state=OUTBOX_STATE_PENDING,
    )
    overlong_token = recovery.ProjectionRecovery(
        entry_id=new_workspace_id(),
        revision_id=new_workspace_id(),
        operation="x" * 200,
        previous_state=OUTBOX_STATE_DEAD_LETTER,
        result=recovery.RECOVERY_RESULT_REQUEUED,
        outbox_state=OUTBOX_STATE_PENDING,
    )

    for smuggled in (free_text_id, overlong_token):
        with pytest.raises(EvidenceLedgerContractError):
            recovery._audit_details(smuggled)
