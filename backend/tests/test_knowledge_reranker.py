"""Cross-encoder reranker: opt-in resolution and chunk reordering."""

from __future__ import annotations

from app.services.knowledge_retrieval import reranker as reranker_module
from app.services.knowledge_retrieval.reranker import rerank_chunks, resolve_reranker_model


def test_reranker_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OCTRYX_KNOWLEDGE_RERANKER_MODEL", raising=False)
    assert resolve_reranker_model() is None
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER_MODEL", "off")
    assert resolve_reranker_model() is None
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER_MODEL", "BAAI/bge-reranker-base")
    assert resolve_reranker_model() == "BAAI/bge-reranker-base"


def test_rerank_chunks_reorders_by_cross_encoder(monkeypatch):
    chunks = [
        {"id": "a", "text": "unrelated content about databases"},
        {"id": "b", "text": "the payment service charges credit cards"},
        {"id": "c", "text": "kubernetes pod restart policy"},
    ]

    def fake_scores(query, texts, *, model):
        return [0.1 if "payment" not in t else 0.9 for t in texts]

    monkeypatch.setattr(reranker_module, "rerank_texts", fake_scores)
    ranked = rerank_chunks("how are cards charged?", chunks, model="stub", limit=2)
    assert ranked[0]["id"] == "b"
    assert ranked[0]["rerank_score"] == 0.9
    assert len(ranked) == 2


def test_rerank_failure_keeps_original_order(monkeypatch):
    chunks = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]

    def boom(query, texts, *, model):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(reranker_module, "rerank_texts", boom)
    ranked = rerank_chunks("q", chunks, model="stub", limit=2)
    assert [c["id"] for c in ranked] == ["a", "b"]
