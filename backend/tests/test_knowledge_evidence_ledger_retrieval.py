"""The end-to-end slice from upload to projection, retrieval and citation: retrieval is bounded, whole-word and Unicode-folded."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project.knowledge_evidence import (
    OUTBOX_STATE_APPLIED,
    REVISION_STATE_PROJECTED,
    REVISION_STATE_REGISTERED,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.retrieval.lexical_recall import ranking_terms
from app.services.knowledge.retrieval.lexical_terms import fold
from tests.knowledge_evidence_ledger_support import FIRST, _authorized, _ingest
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace

# --- end to end -------------------------------------------------------------


async def test_upload_projection_retrieval_and_citation(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, evidence_index = build_runtime()

    ingested = await _ingest(db, runtime, authorized, FIRST)

    # Before projection, retrieval is an explicit state (projection_pending, E1), never an empty result.
    from app.services.knowledge.ledger.errors import EvidenceProjectionPendingError

    with pytest.raises(EvidenceProjectionPendingError):
        await retrieve_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text="datacenter"
        )

    outcome = await EvidenceProjector(runtime).project_once(db, worker_id="test-worker")
    assert outcome is not None and outcome.applied is True
    assert outcome.spans_projected == ingested.span_count

    result = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="datacenter", limit=5
    )
    assert result.dropped_unresolved == 0
    assert len(result.evidence) == 1
    hit = result.evidence[0]
    assert "Zurich datacenter" in hit.text
    assert hit.revision_id == ingested.revision_id
    assert hit.span_ordinal == 1
    assert hit.content_sha256 == ingested.content_sha256
    assert f"rev {ingested.revision_ordinal}" in hit.citation
    assert hit.evidence_key == derive_evidence_key(ingested.revision_id, 1)

    revision = await db.get(KnowledgeSourceRevision, ingested.revision_id)
    assert revision is not None and revision.state == REVISION_STATE_PROJECTED
    entry = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.state).where(
                KnowledgeProjectionOutboxEntry.revision_id == ingested.revision_id
            )
        )
    ).scalar_one()
    assert entry == OUTBOX_STATE_APPLIED


async def test_retrieval_is_bounded_and_whole_word_only(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, evidence_index = build_runtime()
    payload = "\n\n".join(f"Paragraph {index} mentions datacenter capacity." for index in range(12)).encode()

    await _ingest(db, runtime, authorized, payload)
    await EvidenceProjector(runtime).project_once(db, worker_id="test-worker")

    bounded = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="datacenter", limit=3
    )
    assert len(bounded.evidence) == 3

    # No prefix matching: a partial token matches nothing.
    empty = await retrieve_workspace_evidence(
        db, runtime=runtime, authorized=authorized, query_text="datac"
    )
    assert empty.evidence == ()


def test_ranking_compares_unicode_in_one_folded_form():
    """Finding 7: a non-ASCII word is one term, and composition never decides a hit."""
    assert ranking_terms("Zürich MÜLLER naïve") == ("zürich", "müller", "naïve")
    # Composed and decomposed spellings fold to the same comparison form, so a query
    # in either form scores its hit instead of ranking last and being cut.
    assert fold("café") == fold("café")
    assert ranking_terms("café")[0] in fold("Le CAFÉ est ouvert")
    # Deterministic: insertion-ordered, de-duplicated, independent of locale.
    assert ranking_terms("beta Beta BETA alpha") == ("beta", "alpha")


async def test_unicode_retrieval_ranks_the_matching_span_first(db):
    """Finding 7: a non-ASCII match is ordered by its hit, not dropped to the tail."""
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, evidence_index = build_runtime()
    payload = (
        "Ein Absatz ohne besondere Zeichen.\n\n"
        "Zürich betreibt den primären Cluster.\n\n"
        "Genève héberge le basculement.\n\n"
        "Noch ein Absatz ohne besondere Zeichen.\n"
    ).encode()
    await _ingest(db, runtime, authorized, payload)
    await EvidenceProjector(runtime).project_once(db, worker_id="test-worker")

    for query, fragment in (("Zürich", "Zürich"), ("Genève", "Genève"), ("primären", "primären")):
        # limit=1 is the point: an unranked non-ASCII match would be cut here.
        result = await retrieve_workspace_evidence(
            db, runtime=runtime, authorized=authorized, query_text=query, limit=1
        )
        assert len(result.evidence) == 1, query
        assert fragment in result.evidence[0].text

    repeated = [
        tuple(
            item.evidence_key
            for item in (
                await retrieve_workspace_evidence(
                    db, runtime=runtime, authorized=authorized, query_text="Absatz Zürich"
                )
            ).evidence
        )
        for _ in range(3)
    ]
    assert len(set(repeated)) == 1  # the same corpus and query always order the same


async def test_a_registered_revision_starts_unprojected(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, _, _ = build_runtime()
    ingested = await _ingest(db, runtime, authorized, FIRST)
    revision = await db.get(KnowledgeSourceRevision, ingested.revision_id)
    assert revision is not None
    assert revision.state == REVISION_STATE_REGISTERED and revision.projected_at is None
