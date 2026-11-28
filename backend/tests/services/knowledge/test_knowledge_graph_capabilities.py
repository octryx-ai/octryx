"""What the Relationships page is told about this installation's graph (``GET .../knowledge/graph``):
extraction is offered only where the Evidence runtime and an embedding space exist."""

from __future__ import annotations

import dataclasses

from app.api.routes.knowledge import knowledge_graph
from app.services.knowledge.embedding.catalog import embedding_space
from app.services.knowledge.embedding.port import EmbeddingRuntime
from app.services.knowledge.ledger.errors import EvidenceStoreNotConfiguredError
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_text_support import ConceptEmbedder

LOCAL = embedding_space("local_mlminilm_384_v1")


def _with(monkeypatch, runtime):
    monkeypatch.setattr(knowledge_graph, "get_evidence_runtime", lambda: runtime)
    return knowledge_graph._capabilities()


def test_no_runtime_means_nothing_to_read_or_extract(monkeypatch):
    def unconfigured():
        raise EvidenceStoreNotConfiguredError()

    monkeypatch.setattr(knowledge_graph, "get_evidence_runtime", unconfigured)
    assert knowledge_graph._capabilities() == {"readable": False, "extractable": False}


def test_the_graph_reads_and_extracts_with_an_embedding_space(monkeypatch):
    embedding = EmbeddingRuntime(space=LOCAL, embedder=ConceptEmbedder(LOCAL))
    runtime, _, _ = build_runtime(embedding=embedding)
    assert _with(monkeypatch, runtime) == {"readable": True, "extractable": True}
    # Without an embedding space neither works: ranking and extraction both need it.
    assert _with(monkeypatch, dataclasses.replace(runtime, embedding=None)) == {"readable": False, "extractable": False}
