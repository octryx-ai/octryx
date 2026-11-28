"""The race between an object hold and an in-flight ingestion."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.project.knowledge_evidence import (
    REVISION_STATE_REGISTERED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
)
from app.models.project.knowledge_object_retention import KnowledgeObjectRetentionHold
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceStoreUnavailableError
from app.services.knowledge.retention.holds import MIN_HOLD_SECONDS, acquire_hold, object_key_is_held
from app.services.knowledge.retention.reconcile import reconcile_workspace
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.services.knowledge.knowledge_retention_support import FakeMaintenanceClient, maintenance
from tests.support.knowledge_evidence_s3_support import BUCKET

ABANDONED = b"Bytes whose ledger transaction never committed.\n\nSecond paragraph.\n"
OPERATOR = "cli:acceptance"
OTHER_OPERATOR = "cli:another"


async def _no_sleep(_seconds: float) -> None:
    return None


def _wired():
    client = FakeMaintenanceClient()
    runtime, _, _ = build_runtime(s3=client.source)
    return runtime, maintenance(client), client


async def _authorized(db, workspace_id: str):
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    user = await fetch_user(db, user_id)
    return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)


async def _abandon(runtime, client, authorized, *, age_hours: int = 200) -> str:
    stored = await runtime.object_store.put_if_absent(authorized.workspace, ABANDONED)
    client.age(stored.ref.key, hours=age_hours)
    return stored.ref.key


async def _observed_finding(db, maintain, client, runtime, authorized) -> tuple[str, str]:
    key = await _abandon(runtime, client, authorized)
    report = await reconcile_workspace(
        db, maintenance=maintain, project_id=authorized.project_id, requested_by=OPERATOR
    )
    return key, report.findings[0].finding_id


async def _ingest(db, runtime, authorized, payload: bytes, *, source_key: str = "runbook"):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title="Runbook",
        declared_media_type="text/plain",
        data=payload,
        created_by=authorized.project_id,
    )


async def _revision_count(db, project_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count(KnowledgeSourceRevision.id)).where(
                    KnowledgeSourceRevision.project_id == project_id
                )
            )
        ).scalar_one()
    )


async def _commit_reference(db, authorized, key: str) -> None:
    source_id = str(uuid.uuid4())
    db.add(
        KnowledgeEvidenceSource(
            id=source_id,
            project_id=authorized.project_id,
            source_key=f"in-flight-{source_id[:8]}",
            display_title="In-flight ingestion",
        )
    )
    await db.flush()
    db.add(
        KnowledgeSourceRevision(
            id=str(uuid.uuid4()),
            source_id=source_id,
            project_id=authorized.project_id,
            revision_ordinal=1,
            content_sha256="0" * 64,
            byte_size=len(ABANDONED),
            media_type="text/plain",
            object_bucket=BUCKET,
            object_key=key,
            parser_name="text",
            parser_version="1",
            parser_sandbox="none",
            state=REVISION_STATE_REGISTERED,
            span_count=1,
        )
    )
    await db.commit()


async def test_an_ingestion_defers_instead_of_referencing_a_held_object(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    key, finding_id = await _observed_finding(db, maintain, client, runtime, authorized)

    hold = await acquire_hold(
        db,
        project_id=workspace_id,
        object_key=key,
        finding_id=finding_id,
        acquired_by=OPERATOR,
    )

    assert hold is not None
    assert await object_key_is_held(db, project_id=workspace_id, object_key=key) is True
    # Re-uploading exactly the abandoned bytes is the dangerous path: the object is already
    # there (412), so the revision would point at bytes a retention pass is about to remove.
    with pytest.raises(EvidenceStoreUnavailableError):
        await _ingest(db, runtime, authorized, ABANDONED)
    assert await _revision_count(db, workspace_id) == 0
    other_id = await seed_workspace(db)
    other = await _authorized(db, other_id)
    assert (await _ingest(db, runtime, other, ABANDONED)).revision_ordinal == 1


async def test_a_hold_of_another_pass_is_never_taken_over_while_it_is_live(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    key, finding_id = await _observed_finding(db, maintain, client, runtime, authorized)
    first = await acquire_hold(
        db, project_id=workspace_id, object_key=key, finding_id=finding_id, acquired_by=OTHER_OPERATOR
    )

    second = await acquire_hold(
        db, project_id=workspace_id, object_key=key, finding_id=finding_id, acquired_by=OPERATOR
    )

    assert first is not None and second is None
    assert await object_key_is_held(db, project_id=workspace_id, object_key=key) is True
    assert (maintain.bucket, key) in client.source.objects


async def test_one_hold_per_object_is_a_database_guarantee(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    key, finding_id = await _observed_finding(db, maintain, client, runtime, authorized)
    await acquire_hold(
        db, project_id=workspace_id, object_key=key, finding_id=finding_id, acquired_by=OPERATOR
    )

    db.add(
        KnowledgeObjectRetentionHold(
            id="22222222-2222-4222-8222-222222222222",
            project_id=workspace_id,
            object_key=key,
            finding_id=finding_id,
            acquired_by=OTHER_OPERATOR,
            acquired_at=utc_now(),
            expires_at=utc_now() + timedelta(seconds=MIN_HOLD_SECONDS),
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_an_expired_hold_blocks_nothing_and_is_taken_over(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    key, finding_id = await _observed_finding(db, maintain, client, runtime, authorized)
    db.add(
        KnowledgeObjectRetentionHold(
            id="33333333-3333-4333-8333-333333333333",
            project_id=workspace_id,
            object_key=key,
            finding_id=finding_id,
            acquired_by=OTHER_OPERATOR,
            acquired_at=utc_now() - timedelta(hours=2),
            expires_at=utc_now() - timedelta(hours=1),
        )
    )
    await db.commit()

    assert await object_key_is_held(db, project_id=workspace_id, object_key=key) is False
    taken = await acquire_hold(
        db, project_id=workspace_id, object_key=key, finding_id=finding_id, acquired_by=OPERATOR
    )

    assert taken is not None and taken.hold_id != "33333333-3333-4333-8333-333333333333"
    rows = (
        (
            await db.execute(
                select(KnowledgeObjectRetentionHold).where(
                    KnowledgeObjectRetentionHold.project_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].acquired_by == OPERATOR
