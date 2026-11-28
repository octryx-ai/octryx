"""Shared helpers for the test_knowledge_projection_recovery_* modules."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.main import app
from app.models.project.knowledge_evidence import (
    DEFAULT_MAX_PROJECTION_ATTEMPTS,
    OUTBOX_STATE_DEAD_LETTER,
    PROJECTION_FAILURE_UNAVAILABLE,
    KnowledgeProjectionOutboxEntry,
)
from app.models.security.compliance_audit import ComplianceAuditRecord
from app.services.auth import get_current_user
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection import recovery, recovery_vocabulary
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_runtime_support import set_evidence_runtime

BASE = "/api/v1/workspaces"


PAYLOAD = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


REQUEUE = recovery_vocabulary.RECOVERY_OPERATION_REQUEUE


@pytest.fixture
def as_user(db):
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


async def _ingested(db, *, role: str = "admin"):
    workspace_id = await seed_workspace(db)
    user = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role=role))
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    authorized = await authorize_workspace(
        db, current_user=user, workspace_id=workspace_id, require_author=True
    )
    ingested = await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="runbook",
        display_title="Runbook",
        declared_media_type="text/plain",
        data=PAYLOAD,
        created_by=user.id,
    )
    return workspace_id, user, authorized, runtime, evidence_index, ingested


async def _dead_lettered(db, *, role: str = "admin"):
    prepared = await _ingested(db, role=role)
    await _force(
        db,
        prepared[5].revision_id,
        state=OUTBOX_STATE_DEAD_LETTER,
        attempt_count=DEFAULT_MAX_PROJECTION_ATTEMPTS,
        last_failure=PROJECTION_FAILURE_UNAVAILABLE,
        next_attempt_at=utc_now() + timedelta(hours=1),
    )
    return prepared


async def _entry(db, revision_id: str) -> KnowledgeProjectionOutboxEntry:
    return (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry)
            .where(KnowledgeProjectionOutboxEntry.revision_id == revision_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _force(db, revision_id: str, **values) -> None:
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.revision_id == revision_id)
        .values(**values)
    )
    await db.commit()


async def _drop_obligation(db, revision_id: str) -> None:
    await db.execute(
        KnowledgeProjectionOutboxEntry.__table__.delete().where(
            KnowledgeProjectionOutboxEntry.revision_id == revision_id
        )
    )
    await db.commit()


async def _audit_records(db, project_id: str) -> list[ComplianceAuditRecord]:
    return list(
        (
            await db.execute(
                select(ComplianceAuditRecord)
                .where(ComplianceAuditRecord.project_id == project_id)
                .order_by(ComplianceAuditRecord.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _recover(db, authorized, revision_id, operation=REQUEUE, actor_user_id=None):
    return await recovery.recover_projection(
        db,
        authorized=authorized,
        revision_id=revision_id,
        operation=operation,
        actor_user_id=actor_user_id,
    )


def _url(workspace_id: str, revision_id: str, suffix: str) -> str:
    return f"{BASE}/{workspace_id}/knowledge/projection/revisions/{revision_id}/{suffix}"


@pytest.fixture(autouse=True)
def _release_evidence_runtime():
    yield
    set_evidence_runtime(None)
