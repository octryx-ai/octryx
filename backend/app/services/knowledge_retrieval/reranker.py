"""Optional cross-encoder reranker for retrieved passages.

Explicit opt-in: it only runs when ``knowledge_reranker_model`` is configured
(settings/.env) — a per-query model pass must never be a silent default. The
cross-encoder scores (query, passage) pairs jointly, which reorders the
candidate list far more precisely than bi-encoder similarity alone; weak answer
models benefit most because the context budget fills with the RIGHT passages.

Model guidance (measured): ``BAAI/bge-reranker-base`` (Apache-2.0)
and ``Xenova/ms-marco-MiniLM-L-12-v2`` rank ENGLISH queries precisely but fail
on German queries (flat scores) — do not enable them on German-language
instances. jina-reranker-v2-base-multilingual would handle German but is
CC-BY-NC licensed, unsuitable as a product default. Hence: off by default.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from app.services.error_facts import error_text

logger = logging.getLogger(__name__)

KNOWLEDGE_RERANKER_MODEL_ENV = "OCTRYX_KNOWLEDGE_RERANKER_MODEL"


def resolve_reranker_model() -> str | None:
    """Resolve the configured reranker model (env first, then settings).
    ``None`` means reranking is off — the explicit default."""
    configured = str(os.environ.get(KNOWLEDGE_RERANKER_MODEL_ENV) or "").strip()
    if not configured:
        from ...config import get_settings

        configured = str(getattr(get_settings(), "knowledge_reranker_model", None) or "").strip()
    normalized = configured.lower()
    if not configured or normalized in {"off", "none", "disabled"}:
        return None
    return configured


@lru_cache(maxsize=4)
def _load_cross_encoder(model: str) -> Any:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model)


def rerank_texts(query: str, texts: list[str], *, model: str) -> list[float]:
    """Score (query, text) pairs with the cross-encoder; higher is better."""
    if not texts:
        return []
    encoder = _load_cross_encoder(model)
    return [float(score) for score in encoder.rerank(query, texts)]


def rerank_chunks(
    query: str, chunks: list[dict[str, Any]], *, model: str, limit: int
) -> list[dict[str, Any]]:
    """Reorder chunk candidates by cross-encoder relevance and cut to ``limit``.
    Falls back to the original ranking if the reranker fails (logged loudly)."""
    if len(chunks) <= 1:
        return chunks[:limit]
    try:
        scores = rerank_texts(query, [str(chunk.get("text") or "") for chunk in chunks], model=model)
    except Exception as exc:  # noqa: BLE001 - retrieval must not fail on reranking
        logger.warning(
            "Reranker '%s' failed; keeping bi-encoder order: %s", model, error_text("reranker_failed", exc)
        )
        return chunks[:limit]
    reranked = [
        {**chunk, "rerank_score": round(score, 6)}
        for chunk, score in sorted(zip(chunks, scores), key=lambda pair: -pair[1])
    ]
    return reranked[:limit]
