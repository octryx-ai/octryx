"""Shared helpers for the test_knowledge_evidence_projection_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models.project.knowledge_evidence import KnowledgeProjectionOutboxEntry
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex

PAYLOAD = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


async def _authorized(db, workspace_id: str):
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    return await authorize_workspace(
        db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id, require_author=True
    )


async def _prepared(
    db, *, index: FakeEvidenceIndex | None = None, payload: bytes = PAYLOAD
):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, s3, evidence_index = build_runtime(index=index)
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
    return authorized, runtime, s3, evidence_index, ingested


async def _entry(db, revision_id: str) -> KnowledgeProjectionOutboxEntry:
    return (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry).where(
                KnowledgeProjectionOutboxEntry.revision_id == revision_id
            )
        )
    ).scalar_one()
