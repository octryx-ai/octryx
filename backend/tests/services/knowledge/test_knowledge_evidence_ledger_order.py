"""Insert order and atomicity of one ledger registration."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import event, select

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_PENDING,
    KnowledgeEvidenceSource,
    KnowledgeProjectionOutboxEntry,
)
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.ledger import revision_rows
from app.services.knowledge.ledger.errors import EvidenceLedgerContractError
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.services.knowledge.knowledge_evidence_ledger_order_support import (
    FIRST,
    SECOND,
    _author,
    _ingest,
    _ledger_counts,
)

REVISIONS = "knowledge_source_revisions"


SPANS = "knowledge_evidence_spans"


OUTBOX = "knowledge_projection_outbox"


@contextmanager
def _recorded_statements(sync_connection) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(" ".join(statement.split())[:60])

    event.listen(sync_connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync_connection, "before_cursor_execute", record)


def _inserted_into(statements: list[str], table: str) -> list[int]:
    return [index for index, statement in enumerate(statements) if statement.startswith(f"INSERT INTO {table} ")]


async def test_the_projection_obligation_is_inserted_after_the_revision_it_references(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await _author(db, user_id, workspace_id)
    runtime, _, _ = build_runtime()
    sync_connection = (await db.connection()).sync_connection

    with _recorded_statements(sync_connection) as statements:
        ingested = await _ingest(db, runtime, authorized, FIRST, created_by=user_id)

    revision_inserts = _inserted_into(statements, REVISIONS)
    span_inserts = _inserted_into(statements, SPANS)
    outbox_inserts = _inserted_into(statements, OUTBOX)
    assert len(revision_inserts) == 1 and len(outbox_inserts) == 1 and span_inserts
    # The obligation is written last: its foreign key is only satisfiable once the
    # revision row exists, which is what PostgreSQL enforces per statement.
    assert revision_inserts[0] < min(span_inserts)
    assert max(span_inserts) < outbox_inserts[0]
    # Still one transaction: between the revision and its obligation there are only the
    # span inserts and the new source's head row — no commit, no savepoint.
    between = statements[revision_inserts[0] + 1 : outbox_inserts[0]]
    assert between and all(
        statement.startswith(
            (
                f"INSERT INTO {SPANS} ",
                "INSERT INTO knowledge_source_heads ",
                "INSERT INTO knowledge_source_revision_origins ",
                "INSERT INTO knowledge_revision_scopes ",
            )
        )
        for statement in between
    )

    assert await _ledger_counts(db, workspace_id) == {
        "sources": 1,
        "revisions": 1,
        "spans": ingested.span_count,
        "outbox": 1,
    }
    state = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.state).where(
                KnowledgeProjectionOutboxEntry.revision_id == ingested.revision_id
            )
        )
    ).scalar_one()
    assert state == OUTBOX_STATE_PENDING


async def test_a_registration_refused_at_the_flush_boundary_leaves_no_partial_rows(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await _author(db, user_id, workspace_id)
    runtime, _, _ = build_runtime()
    registered = await _ingest(db, runtime, authorized, FIRST, created_by=user_id, source_key="runbook")
    taken_key = derive_evidence_key(registered.revision_id, 1)
    before = await _ledger_counts(db, workspace_id)

    with patch.object(revision_rows, "derive_evidence_key", lambda *_: taken_key):
        with pytest.raises(EvidenceLedgerContractError):
            await _ingest(db, runtime, authorized, SECOND, created_by=user_id, source_key="policy")

    assert await _ledger_counts(db, workspace_id) == before
    keys = (
        (
            await db.execute(
                select(KnowledgeEvidenceSource.source_key).where(KnowledgeEvidenceSource.project_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    assert keys == ["runbook"]
