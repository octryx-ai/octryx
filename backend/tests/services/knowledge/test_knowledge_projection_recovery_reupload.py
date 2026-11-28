"""Identical uploads recover through the governed service and no second reset rule remains in the package."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.api.routes.knowledge import knowledge_evidence_sources as sources_routes
from app.api.routes.knowledge import knowledge_projection_recovery as recovery_routes
from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_DEAD_LETTER,
    OUTBOX_STATE_PENDING,
    KnowledgeProjectionOutboxEntry,
)
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger import revisions as ledger_module
from app.services.knowledge.projection import recovery_vocabulary
from tests.support.knowledge_projection_recovery_support import (  # noqa: F401
    PAYLOAD,
    _audit_records,
    _dead_lettered,
    _drop_obligation,
    _entry,
    _ingested,
    _release_evidence_runtime,
)


def _served_posts(module) -> set[str]:
    return {
        route.path
        for route in module.router.routes
        if "POST" in (getattr(route, "methods", None) or set())
    }


async def test_an_identical_upload_recovers_through_the_governed_service_with_an_audit_record(db):
    workspace_id, user, authorized, runtime, _, ingested = await _dead_lettered(db)

    repeated = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=PAYLOAD,
        created_by=user.id,
    )

    assert repeated.created is False and repeated.revision_id == ingested.revision_id
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING
    assert entry.attempt_count == 0 and entry.last_failure is None
    records = await _audit_records(db, workspace_id)
    assert len(records) == 1
    assert records[0].details["operation"] == recovery_vocabulary.RECOVERY_OPERATION_REQUEUE_ON_REUPLOAD
    assert records[0].details["previous_state"] == OUTBOX_STATE_DEAD_LETTER
    assert records[0].actor_user_id == user.id


async def test_an_identical_upload_of_a_healthy_revision_changes_and_records_nothing(db):
    workspace_id, user, authorized, runtime, _, ingested = await _ingested(db)
    before = await _entry(db, ingested.revision_id)
    before_state, before_attempts, before_due = before.state, before.attempt_count, before.next_attempt_at

    repeated = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=PAYLOAD,
        created_by=user.id,
    )

    assert repeated.created is False
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == before_state and entry.attempt_count == before_attempts
    assert entry.next_attempt_at == before_due
    assert await _audit_records(db, workspace_id) == []


async def test_an_identical_upload_stays_idempotent_when_the_obligation_is_missing(db):
    workspace_id, user, authorized, runtime, _, ingested = await _ingested(db)
    await _drop_obligation(db, ingested.revision_id)

    repeated = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=PAYLOAD,
        created_by=user.id,
    )

    assert repeated.created is False and repeated.revision_id == ingested.revision_id
    assert (
        await db.execute(
            select(func.count(KnowledgeProjectionOutboxEntry.id)).where(
                KnowledgeProjectionOutboxEntry.revision_id == ingested.revision_id
            )
        )
    ).scalar_one() == 0
    assert await _audit_records(db, workspace_id) == []


def test_the_ledger_holds_no_recovery_rule_of_its_own():
    source = Path(ledger_module.__file__).read_text()
    for forbidden in ("_requeue_dead_letter", "OUTBOX_STATE_DEAD_LETTER", "attempt_count"):
        assert forbidden not in source
    assert "recover_projection" in source


def test_only_the_recovery_service_reads_dead_letter_as_a_source_state():
    package = Path(ledger_module.__file__).parents[1]
    owners = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if "state == OUTBOX_STATE_DEAD_LETTER" in path.read_text()
    )
    assert owners == ["projection/recovery.py"]
    assert "OUTBOX_STATE_DEAD_LETTER if exhausted" in (package / "projection" / "outbox.py").read_text()


def test_the_transport_cannot_request_the_reupload_operation():
    source = Path(recovery_routes.__file__).read_text()
    assert "REQUEUE_ON_REUPLOAD" not in source
    prefix = "/api/v1/workspaces/{workspace_id}/knowledge/projection"
    assert _served_posts(recovery_routes) == {
        f"{prefix}/revisions/{{revision_id}}/requeue",
        f"{prefix}/revisions/{{revision_id}}/retry-now",
    }


def test_the_manual_projection_endpoint_keeps_its_own_path():
    served = _served_posts(sources_routes)
    assert "/api/v1/workspaces/{workspace_id}/knowledge/projection/run" in served
    assert served.isdisjoint(_served_posts(recovery_routes))
