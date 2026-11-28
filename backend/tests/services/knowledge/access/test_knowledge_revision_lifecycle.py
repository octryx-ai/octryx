"""A source serves exactly what it currently says (contract §9.7, §9.8)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    REVISION_STATE_SUPERSEDED,
    REVISION_STATE_TOMBSTONED,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.lifecycle import remove_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.time_utils import utc_now
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

V1 = b"The failover drill runs every Monday.\n"
V2 = b"The failover drill runs every second Tuesday.\n"


async def _setup(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    database = authorized.workspace.canonical
    return authorized, user_id, runtime, evidence_index, database


async def _upload(db, runtime, authorized, user_id, data: bytes):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="drill",
        display_title="Drill plan",
        declared_media_type="text/markdown",
        data=data,
        created_by=user_id,
    )


async def _drain(db, runtime) -> None:
    projector = EvidenceProjector(runtime)
    for _ in range(20):
        if await projector.project_once(db, worker_id="test") is None:
            return
    raise AssertionError("the outbox did not drain")


async def _served(db, runtime, authorized) -> list[str]:
    result = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="drill")
    return [item.text for item in result.evidence]


def _projected_spans_of(evidence_index, database: str, revision_id: str) -> list[str]:
    prefix = f"{uuid.UUID(revision_id).hex}:"
    return [key for key in evidence_index.evidence_keys(database) if key.startswith(prefix)]


async def _states(db, source_id: str) -> list[str]:
    rows = await db.execute(
        select(KnowledgeSourceRevision.state)
        .where(KnowledgeSourceRevision.source_id == source_id)
        .order_by(KnowledgeSourceRevision.revision_ordinal)
    )
    return list(rows.scalars())


async def test_a_new_revision_replaces_the_old_one_everywhere_but_the_ledger(db) -> None:
    authorized, user_id, runtime, evidence_index, database = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, V1)
    await _drain(db, runtime)
    assert await _served(db, runtime, authorized) == [V1.decode().strip()]

    await _upload(db, runtime, authorized, user_id, V2)
    await _drain(db, runtime)

    assert await _served(db, runtime, authorized) == [V2.decode().strip()]
    assert await _states(db, first.source_id) == [REVISION_STATE_SUPERSEDED, REVISION_STATE_PROJECTED]
    assert not _projected_spans_of(evidence_index, database, first.revision_id)


async def test_the_latest_upload_wins_even_when_an_older_projection_finishes_last(db) -> None:
    authorized, user_id, runtime, evidence_index, database = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, V1)
    second = await _upload(db, runtime, authorized, user_id, V2)
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.revision_id == first.revision_id)
        .values(next_attempt_at=utc_now() + timedelta(seconds=1))
    )
    await db.commit()
    projector = EvidenceProjector(runtime)
    finished = await projector.project_once(db, worker_id="test")
    assert finished is not None and finished.revision_id == second.revision_id
    await db.execute(
        update(KnowledgeProjectionOutboxEntry)
        .where(KnowledgeProjectionOutboxEntry.revision_id == first.revision_id)
        .values(next_attempt_at=utc_now())
    )
    await db.commit()
    await _drain(db, runtime)

    assert await _served(db, runtime, authorized) == [V2.decode().strip()]
    assert await _states(db, first.source_id) == [REVISION_STATE_SUPERSEDED, REVISION_STATE_PROJECTED]
    assert not _projected_spans_of(evidence_index, database, first.revision_id)


async def test_uploading_an_earlier_version_again_makes_it_current_again(db) -> None:
    authorized, user_id, runtime, evidence_index, database = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, V1)
    await _drain(db, runtime)
    await _upload(db, runtime, authorized, user_id, V2)
    await _drain(db, runtime)

    again = await _upload(db, runtime, authorized, user_id, V1)
    await _drain(db, runtime)

    assert again.revision_id == first.revision_id and again.created is False
    assert await _served(db, runtime, authorized) == [V1.decode().strip()]
    assert await _states(db, first.source_id) == [REVISION_STATE_PROJECTED, REVISION_STATE_SUPERSEDED]
    assert _projected_spans_of(evidence_index, database, first.revision_id)


async def test_a_removed_source_leaves_retrieval_and_the_database_and_can_come_back(db) -> None:
    authorized, user_id, runtime, evidence_index, database = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, V1)
    await _drain(db, runtime)

    removed = await remove_source(db, authorized=authorized, source_id=first.source_id, actor_id=user_id)
    await _drain(db, runtime)

    assert removed == 1
    assert await _served(db, runtime, authorized) == []
    assert await _states(db, first.source_id) == [REVISION_STATE_TOMBSTONED]
    assert evidence_index.evidence_keys(database) == ()

    await _upload(db, runtime, authorized, user_id, V1)
    await _drain(db, runtime)
    assert await _served(db, runtime, authorized) == [V1.decode().strip()]


async def test_a_source_removed_while_its_projection_is_pending_is_never_served(db) -> None:
    authorized, user_id, runtime, evidence_index, database = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, V1)
    await remove_source(db, authorized=authorized, source_id=first.source_id, actor_id=user_id)
    await _drain(db, runtime)

    assert await _served(db, runtime, authorized) == []
    assert await _states(db, first.source_id) == [REVISION_STATE_TOMBSTONED]
    assert evidence_index.evidence_keys(database) == ()
