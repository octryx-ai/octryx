"""Shared helpers for the test_knowledge_evidence_ledger_order_* modules."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from tests.knowledge_evidence_seed_support import fetch_user

FIRST = b"The Zurich datacenter hosts the primary cluster.\n\nFailover runs from Geneva.\n"


SECOND = b"The Zurich datacenter hosts the primary cluster.\n\nFailover now runs from Bern.\n"


async def _author(db: AsyncSession, user_id: str, workspace_id: str):
    user = await fetch_user(db, user_id)
    return await authorize_workspace(db, current_user=user, workspace_id=workspace_id, require_author=True)


async def _ingest(
    db: AsyncSession, runtime, authorized, payload: bytes, *, created_by: str, source_key: str = "runbook"
):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=source_key,
        display_title=source_key.title(),
        declared_media_type="text/plain; charset=utf-8",
        data=payload,
        # A real user id: ``created_by`` is a users foreign key, which PostgreSQL
        # enforces and the SQLite harness does not.
        created_by=created_by,
    )


async def _ledger_counts(db: AsyncSession, workspace_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, model in (
        ("sources", KnowledgeEvidenceSource),
        ("revisions", KnowledgeSourceRevision),
        ("spans", KnowledgeEvidenceSpan),
        ("outbox", KnowledgeProjectionOutboxEntry),
    ):
        counts[name] = (
            await db.execute(select(func.count()).select_from(model).where(model.project_id == workspace_id))
        ).scalar_one()
    return counts
