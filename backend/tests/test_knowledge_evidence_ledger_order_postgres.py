"""On PostgreSQL one registration writes the whole ledger and a refused registration leaves none of its rows behind."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_PENDING,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.ledger import revision_rows
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError
from tests.knowledge_evidence_ledger_order_support import FIRST, SECOND, _author, _ingest, _ledger_counts
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.postgres_env import postgres_url

POSTGRES_URL_ENV = "OCTRYX_TEST_LEDGER_POSTGRES_URL"


requires_ledger_postgres = pytest.mark.skipif(
    not postgres_url("LEDGER_POSTGRES_URL"),
    reason=f"set {POSTGRES_URL_ENV} to a disposable PostgreSQL database migrated to head",
)


# --- PostgreSQL -------------------------------------------------------------


async def _purge(session: AsyncSession, workspace_id: str) -> None:
    from app.models import Project, User
    from app.models.security.user import UserProject

    user_ids = (
        (await session.execute(select(UserProject.user_id).where(UserProject.project_id == workspace_id)))
        .scalars()
        .all()
    )
    for model in (
        KnowledgeProjectionOutboxEntry,
        KnowledgeEvidenceSpan,
        KnowledgeSourceHead,  # points at revisions: goes first (PostgreSQL checks the key)
        KnowledgeSourceRevision,
        KnowledgeEvidenceSource,
    ):
        await session.execute(delete(model).where(model.project_id == workspace_id))
    await session.execute(delete(UserProject).where(UserProject.project_id == workspace_id))
    if user_ids:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.execute(delete(Project).where(Project.id == workspace_id))
    await session.commit()


@requires_ledger_postgres
async def test_postgresql_registers_the_whole_ledger_and_keeps_a_refused_one_out():
    """The real engine: one ingestion commits, one refused ingestion leaves nothing.

    This is the acceptance the SQLite harness cannot give. PostgreSQL enforces
    ``knowledge_projection_outbox_revision_id_fkey`` per statement, so a committed
    pending obligation here is proof the revision was inserted first.
    """
    # NullPool: no connection outlives this test's event loop.
    engine = create_async_engine(postgres_url("LEDGER_POSTGRES_URL"), poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    workspace_id = ""
    try:
        async with factory() as session:
            workspace_id = await seed_workspace(session)
            user_id = await seed_member(session, workspace_id=workspace_id, role="admin")
            await session.commit()

        async with factory() as session:
            authorized = await _author(session, user_id, workspace_id)
            runtime, s3, _ = build_runtime()
            ingested = await _ingest(session, runtime, authorized, FIRST, created_by=user_id, source_key="runbook")
            assert ingested.created is True and ingested.span_count == 2
            assert len(s3.objects) == 1

        # Re-read on a fresh session: only committed rows can answer.
        async with factory() as session:
            assert await _ledger_counts(session, workspace_id) == {
                "sources": 1,
                "revisions": 1,
                "spans": 2,
                "outbox": 1,
            }
            entry = (
                await session.execute(
                    select(KnowledgeProjectionOutboxEntry.state, KnowledgeProjectionOutboxEntry.revision_id).where(
                        KnowledgeProjectionOutboxEntry.project_id == workspace_id
                    )
                )
            ).one()
            assert entry == (OUTBOX_STATE_PENDING, ingested.revision_id)
            ordinals = (
                (
                    await session.execute(
                        select(KnowledgeEvidenceSpan.span_ordinal)
                        .where(KnowledgeEvidenceSpan.revision_id == ingested.revision_id)
                        .order_by(KnowledgeEvidenceSpan.span_ordinal)
                    )
                )
                .scalars()
                .all()
            )
            assert ordinals == [1, 2]

        async with factory() as session:
            authorized = await _author(session, user_id, workspace_id)
            runtime, _, _ = build_runtime()
            taken_key = derive_evidence_key(ingested.revision_id, 1)
            with patch.object(revision_rows, "derive_evidence_key", lambda *_: taken_key):
                with pytest.raises(EvidenceLedgerContractError):
                    await _ingest(session, runtime, authorized, SECOND, created_by=user_id, source_key="policy")

        async with factory() as session:
            assert await _ledger_counts(session, workspace_id) == {
                "sources": 1,
                "revisions": 1,
                "spans": 2,
                "outbox": 1,
            }
    finally:
        if workspace_id:
            async with factory() as session:
                await _purge(session, workspace_id)
        await engine.dispose()
