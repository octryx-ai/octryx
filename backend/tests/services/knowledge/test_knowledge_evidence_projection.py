"""Outbox projection: no fallback, bounded retry, dead-letter, exactly once."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.models.project.knowledge_evidence import (
    ALL_PROJECTION_FAILURES,
    OUTBOX_STATE_PENDING,
    PROJECTION_FAILURE_UNAVAILABLE,
    REVISION_STATE_REGISTERED,
    KnowledgeSourceRevision,
)
from app.services.knowledge.ledger.errors import (
    EvidenceLedgerContractError,
    EvidenceProjectionPendingError,
)
from app.services.knowledge.projection import projector as projector_module
from app.services.knowledge.projection.outbox import claim_next, mark_failed
from app.services.knowledge.projection.outbox_lease import DEFAULT_LEASE_SECONDS
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.errors import KnowledgeIndexUnavailableError
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.knowledge.knowledge_evidence_projection_support import _entry, _prepared
from tests.support.knowledge_evidence_index_support import FakeEvidenceIndex


async def test_an_unavailable_projection_leaves_a_pending_obligation(db):
    authorized, runtime, _, evidence_index, ingested = await _prepared(db, index=FakeEvidenceIndex(unavailable=True))

    outcome = await EvidenceProjector(runtime).project_once(db, worker_id="worker-a")

    assert outcome is not None
    assert outcome.applied is False
    assert outcome.failure == PROJECTION_FAILURE_UNAVAILABLE
    assert outcome.outbox_state == OUTBOX_STATE_PENDING
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING
    assert entry.attempt_count == 1
    assert entry.last_failure in ALL_PROJECTION_FAILURES
    assert entry.applied_at is None
    revision = await db.get(KnowledgeSourceRevision, ingested.revision_id)
    assert revision is not None and revision.state == REVISION_STATE_REGISTERED


async def test_a_slow_projection_times_out_before_lease_expiry_and_counts_the_attempt(db):
    assert projector_module.PROJECTION_RUN_TIMEOUT_SECONDS < DEFAULT_LEASE_SECONDS
    _, runtime, _, _, ingested = await _prepared(db)
    projector = EvidenceProjector(runtime)

    async def slow_batch(*_args):
        await asyncio.sleep(0.05)

    with (
        patch.object(projector, "_project_batch", slow_batch),
        patch.object(projector_module, "PROJECTION_RUN_TIMEOUT_SECONDS", 0.01),
    ):
        outcome = await projector.project_once(db, worker_id="worker-a")

    assert outcome is not None and outcome.failure == PROJECTION_FAILURE_UNAVAILABLE
    entry = await _entry(db, ingested.revision_id)
    assert entry.state == OUTBOX_STATE_PENDING
    assert entry.attempt_count == 1 and entry.last_failure == PROJECTION_FAILURE_UNAVAILABLE


async def test_retrieval_after_a_failed_projection_is_a_typed_state_not_a_fallback(db):
    authorized, runtime, _, _, _ = await _prepared(db, index=FakeEvidenceIndex(unavailable=True))
    await EvidenceProjector(runtime).project_once(db, worker_id="worker-a")

    with pytest.raises(EvidenceProjectionPendingError):
        await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="datacenter")


async def test_a_failure_token_outside_the_fixed_set_is_refused(db):
    _, runtime, _, _, ingested = await _prepared(db)
    claimed = await claim_next(db, worker_id="worker-a")
    assert claimed is not None
    with pytest.raises(EvidenceLedgerContractError):
        await mark_failed(db, claimed, "database said: record #1:0 duplicate key")
    assert (await _entry(db, ingested.revision_id)).last_failure is None


async def test_vector_and_graph_are_explicitly_unavailable(db):
    _, runtime, _, _, _ = await _prepared(db)
    from app.services.knowledge.identity.workspace import WorkspaceId
    from app.services.knowledge.retrieval.contracts import RetrievalMode, RetrievalRequest

    request = RetrievalRequest(
        workspace=WorkspaceId.parse(await seed_workspace(db)),
        query_text="datacenter",
        modes=frozenset({RetrievalMode.LEXICAL}),
    )
    with pytest.raises(KnowledgeIndexUnavailableError) as vector:
        await runtime.query_store.search_vector(request)
    assert vector.value.mode == "vector"
    with pytest.raises(KnowledgeIndexUnavailableError) as graph:
        await runtime.query_store.search_graph(request)
    assert graph.value.mode == "graph"
