"""Ledger idempotency, span/citation lineage, and the end-to-end slice."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_PENDING,
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.ledger import revisions as ledger
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError, EvidenceStoreUnavailableError
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.support.knowledge_evidence_ledger_support import FIRST, SECOND, _authorized, _ingest


async def test_the_same_bytes_twice_are_one_revision_and_one_object(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, s3, _ = build_runtime()

    first = await _ingest(db, runtime, authorized, FIRST)
    second = await _ingest(db, runtime, authorized, FIRST)

    assert first.created is True and second.created is False
    assert first.revision_id == second.revision_id
    assert first.revision_ordinal == second.revision_ordinal == 1
    assert len(s3.objects) == 1
    revisions = (
        await db.execute(
            select(KnowledgeSourceRevision.id).where(KnowledgeSourceRevision.project_id == workspace_id)
        )
    ).scalars().all()
    assert len(revisions) == 1
    entries = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.state).where(
                KnowledgeProjectionOutboxEntry.project_id == workspace_id
            )
        )
    ).scalars().all()
    assert entries == [OUTBOX_STATE_PENDING]


async def test_changed_bytes_are_a_new_immutable_revision(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, s3, _ = build_runtime()

    first = await _ingest(db, runtime, authorized, FIRST)
    second = await _ingest(db, runtime, authorized, SECOND)

    assert second.created is True
    assert second.revision_id != first.revision_id
    assert (first.revision_ordinal, second.revision_ordinal) == (1, 2)
    assert first.source_id == second.source_id
    assert first.content_sha256 != second.content_sha256
    assert len(s3.objects) == 2
    assert len(s3.puts) == 2


async def test_span_ordinals_and_evidence_keys_are_stable(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()

    ingested = await _ingest(db, runtime, authorized, FIRST)

    spans = (
        await db.execute(
            select(KnowledgeEvidenceSpan)
            .where(KnowledgeEvidenceSpan.revision_id == ingested.revision_id)
            .order_by(KnowledgeEvidenceSpan.span_ordinal)
        )
    ).scalars().all()
    assert [span.span_ordinal for span in spans] == [1, 2]
    assert ingested.span_count == 2
    for span in spans:
        assert span.evidence_key == derive_evidence_key(ingested.revision_id, span.span_ordinal)
        assert span.project_id == workspace_id
        assert f"rev {ingested.revision_ordinal}" in span.citation
        assert f"{span.char_start}-{span.char_end}" in span.citation
        assert span.char_end > span.char_start


async def test_two_sources_in_one_workspace_keep_separate_ordinals(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()

    first = await _ingest(db, runtime, authorized, FIRST, source_key="runbook", title="Runbook")
    second = await _ingest(db, runtime, authorized, FIRST, source_key="policy", title="Policy")

    assert first.source_id != second.source_id
    assert first.revision_ordinal == second.revision_ordinal == 1
    assert first.content_sha256 == second.content_sha256


async def test_a_lost_ordinal_race_is_retried_with_a_recomputed_ordinal(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()
    await _ingest(db, runtime, authorized, FIRST)

    real_next_ordinal = ledger._next_ordinal
    attempts: list[int] = []

    async def stale_on_the_first_attempt(session, project_id, source_id):
        attempts.append(1)
        if len(attempts) == 1:
            return 1
        return await real_next_ordinal(session, project_id, source_id)

    with patch.object(ledger, "_next_ordinal", stale_on_the_first_attempt):
        second = await _ingest(db, runtime, authorized, SECOND)

    assert len(attempts) == 2
    assert second.created is True and second.revision_ordinal == 2


async def test_an_unattributable_integrity_failure_is_refused_not_retried(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()
    await _ingest(db, runtime, authorized, FIRST)

    inserts: list[int] = []

    async def unattributable(*args, **kwargs):
        inserts.append(1)
        raise ledger._RevisionInsertConflictError(stage=ledger._STAGE_REVISION, attempted_ordinal=9999)

    with patch.object(ledger, "_insert_revision", unattributable):
        with pytest.raises(EvidenceLedgerContractError):
            await _ingest(db, runtime, authorized, SECOND)

    assert inserts == [1]


async def test_exhausted_ordinal_contention_is_unavailable_not_a_partial_success(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()
    await _ingest(db, runtime, authorized, FIRST)

    async def always_stale(session, project_id, source_id):
        return 1

    with patch.object(ledger, "_next_ordinal", always_stale):
        with pytest.raises(EvidenceStoreUnavailableError):
            await _ingest(db, runtime, authorized, SECOND)

    remaining = (
        await db.execute(
            select(KnowledgeSourceRevision.revision_ordinal).where(
                KnowledgeSourceRevision.project_id == workspace_id
            )
        )
    ).scalars().all()
    assert remaining == [1]
