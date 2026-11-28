"""Optional cross-encoder reranker for retrieved passages."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from app.services.error_facts import error_text

logger = logging.getLogger(__name__)

KNOWLEDGE_RERANKER_MODEL_ENV = "OCTRYX_KNOWLEDGE_RERANKER_MODEL"


def resolve_reranker_model() -> str | None:
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
    if not texts:
        return []
    encoder = _load_cross_encoder(model)
    return [float(score) for score in encoder.rerank(query, texts)]


def rerank_chunks(
    query: str, chunks: list[dict[str, Any]], *, model: str, limit: int
) -> list[dict[str, Any]]:
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
