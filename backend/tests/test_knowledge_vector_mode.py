"""Vector mode: current revisions get vectors in one space, and paraphrases are found.

The embedder is a deterministic concept model: words of one concept share a dimension. That is
enough to show what lexical search cannot do (find "drill" in a text that says "exercise")
without depending on a real model; the real spaces are exercised live.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EMBED_REVISION,
    OUTBOX_STATE_APPLIED,
    PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED,
    KnowledgeProjectionOutboxEntry,
)
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.embedding.catalog import EMBEDDING_SPACES, embedding_space
from app.services.knowledge.embedding.port import EmbeddingPurpose, EmbeddingRuntime
from app.services.knowledge.evidence_index.operations import OPERATIONS, OperationKind, set_vector_operation
from app.services.knowledge.ingestion.spans import MAX_SPAN_CHARS
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import LEXICAL_MODES, VECTOR_MODES, retrieve_workspace_evidence
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_evidence_text_support import ConceptEmbedder

LOCAL = embedding_space("local_mlminilm_384_v1")
TITAN = embedding_space("bedrock_titan2_1024_v1")


async def _setup(db, *, space=LOCAL):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    embedder = ConceptEmbedder(space)
    runtime, _, evidence_index = build_runtime(embedding=EmbeddingRuntime(space=space, embedder=embedder))
    workspace_id = authorized.workspace.canonical
    return authorized, user_id, runtime, evidence_index, workspace_id, embedder


async def _upload(db, runtime, authorized, user_id, key: str, text: str):
    return await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key=key,
        display_title=key,
        declared_media_type="text/markdown",
        data=text.encode(),
        created_by=user_id,
    )


async def _drain(db, runtime) -> None:
    projector = EvidenceProjector(runtime)
    for _ in range(30):
        if await projector.project_once(db, worker_id="test") is None:
            return
    raise AssertionError("the outbox did not drain")


def test_every_space_has_its_own_vector_write_and_accepts_any_span() -> None:
    for space in EMBEDDING_SPACES.values():
        assert space.max_input_chars >= MAX_SPAN_CHARS  # a span always fits, so nothing is truncated
        spec = OPERATIONS[set_vector_operation(space.key)]
        assert spec.kind is OperationKind.WRITE and spec.parameters == frozenset({"embedding", "evidence_key"})


async def test_vector_mode_finds_the_paraphrase_that_lexical_search_misses(db) -> None:
    authorized, user_id, runtime, evidence_index, workspace_id, embedder = await _setup(db)
    await _upload(db, runtime, authorized, user_id, "runbook", "The failover exercise happens every Tuesday.\n")
    await _upload(db, runtime, authorized, user_id, "vault", "Passwords rotate every month.\n")
    await _drain(db, runtime)

    lexical = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="drill", modes=LEXICAL_MODES
    )
    vector = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="When is the drill?", modes=VECTOR_MODES
    )

    assert lexical.evidence == ()
    assert vector.evidence[0].text == "The failover exercise happens every Tuesday."
    assert vector.evidence[0].score > vector.evidence[-1].score
    assert all(LOCAL.key in record.get("vectors", {}) for record in evidence_index.workspace_records(workspace_id).values())
    assert (EmbeddingPurpose.QUERY, 1) in embedder.calls


async def test_only_the_current_revision_owes_vectors_and_a_replaced_one_leaves(db) -> None:
    authorized, user_id, runtime, evidence_index, workspace_id, _ = await _setup(db)
    first = await _upload(db, runtime, authorized, user_id, "runbook", "The failover exercise happens every Monday.\n")
    await _upload(db, runtime, authorized, user_id, "runbook", "The failover exercise happens every Tuesday.\n")
    await _drain(db, runtime)

    embeds = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.revision_id, KnowledgeProjectionOutboxEntry.state).where(
                KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_EMBED_REVISION
            )
        )
    ).all()
    assert len(embeds) == 1 and embeds[0][0] != first.revision_id and embeds[0][1] == OUTBOX_STATE_APPLIED
    hits = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="drill", modes=VECTOR_MODES
    )
    assert [item.text for item in hits.evidence] == ["The failover exercise happens every Tuesday."]


async def test_a_remote_space_writes_no_vector_for_an_unclassified_workspace(db) -> None:
    authorized, user_id, runtime, evidence_index, workspace_id, embedder = await _setup(db, space=TITAN)
    await _upload(db, runtime, authorized, user_id, "runbook", "The failover exercise happens every Tuesday.\n")
    projector = EvidenceProjector(runtime)
    await projector.project_once(db, worker_id="test")  # the lexical projection
    outcome = await projector.project_once(db, worker_id="test")  # the embedding obligation

    assert outcome is not None and outcome.failure == PROJECTION_FAILURE_EMBEDDING_NOT_CONFIGURED
    assert embedder.calls == []  # nothing left the process
    assert not any(TITAN.key in record.get("vectors", {}) for record in evidence_index.workspace_records(workspace_id).values())
    with pytest.raises(EvidenceStoreNotConfiguredError):
        await retrieve_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text="drill", modes=VECTOR_MODES
        )
    # Lexical retrieval is not held back by the embedding obligation.
    lexical = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="failover")
    assert len(lexical.evidence) == 1


async def test_without_an_embedding_space_nothing_is_owed_and_vector_mode_says_so(db) -> None:
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    await _upload(db, runtime, authorized, user_id, "runbook", "The failover exercise happens every Tuesday.\n")
    await _drain(db, runtime)

    owed = await db.execute(
        select(KnowledgeProjectionOutboxEntry.id).where(
            KnowledgeProjectionOutboxEntry.operation == OUTBOX_OPERATION_EMBED_REVISION
        )
    )
    assert owed.all() == []
    with pytest.raises(EvidenceStoreNotConfiguredError):
        await retrieve_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text="drill", modes=VECTOR_MODES
        )


async def test_a_backfill_owes_vectors_for_revisions_projected_before_a_space_was_configured(db) -> None:
    """Sources projected without an embedding space become searchable by vector after the backfill."""
    from app.services.knowledge.ledger.lifecycle import backfill_embeddings

    authorized, user_id, embedded, evidence_index, _, _ = await _setup(db)
    plain, _, _ = build_runtime(index=evidence_index)  # the same Workspace index, no embedding space yet
    await _upload(db, plain, authorized, user_id, "runbook", "The failover exercise happens every Tuesday.\n")
    await _drain(db, plain)
    # No vectors in this space yet: an explicit state, not an empty or failed search.
    with pytest.raises(EvidenceStoreNotConfiguredError):
        await retrieve_workspace_evidence(
            db, runtime=embedded, authorized=authorized, query_text="drill", modes=VECTOR_MODES
        )

    owed = await backfill_embeddings(db, authorized=authorized, actor_id=user_id, space_key=LOCAL.key)
    await _drain(db, embedded)
    after = await retrieve_workspace_evidence(
        db, runtime=embedded, authorized=authorized, query_text="drill", modes=VECTOR_MODES
    )

    assert owed == 1
    assert [item.text for item in after.evidence] == ["The failover exercise happens every Tuesday."]
