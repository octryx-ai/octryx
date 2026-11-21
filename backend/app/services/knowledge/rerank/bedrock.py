"""Cohere Rerank 3.5 on Bedrock (``invoke_model``).

Request ``{"query", "documents", "top_n", "api_version": 2}``; the response is
``{"results": [{"index", "relevance_score"}]}``. The caller admits the Workspace first. Failures
map to the embedding port's fixed states (``embedding/bedrock.py``); no provider text is kept, and
usage is logged as counts only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from typing import Any

from ..embedding.bedrock import provider_failure
from ..embedding.port import EmbeddingError, EmbeddingState
from .catalog import RerankerSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RerankScore:
    index: int
    relevance: float


class BedrockReranker:
    def __init__(self, spec: RerankerSpec, *, client: Any) -> None:
        self.spec = spec
        self._client = client

    def _invoke(self, query: str, documents: list[str]) -> list[RerankScore]:
        body = {"query": query, "documents": documents, "top_n": len(documents), "api_version": 2}
        try:
            response = self._client.invoke_model(
                modelId=self.spec.model,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(response["body"].read())
        except Exception as error:
            raise provider_failure(error) from None
        results = payload.get("results") if isinstance(payload, dict) else None
        if type(results) is not list:
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
        scores = []
        for item in results:
            index, relevance = (
                (item.get("index"), item.get("relevance_score")) if isinstance(item, dict) else (None, None)
            )
            if type(index) is not int or not 0 <= index < len(documents) or type(relevance) not in (int, float):
                raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
            if not math.isfinite(relevance):
                raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
            scores.append(RerankScore(index=index, relevance=float(relevance)))
        if len({score.index for score in scores}) != len(scores):
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
        return scores

    async def rerank(self, query: str, documents: list[str]) -> list[RerankScore]:
        """Relevance per document index, best first. Bounded by the spec; never an empty request."""
        if not query.strip() or not 0 < len(documents) <= self.spec.max_documents:
            raise EmbeddingError(EmbeddingState.LIMIT_EXCEEDED, "rerank_batch")
        clipped = [document[: self.spec.max_document_chars] for document in documents]
        scores = await asyncio.to_thread(self._invoke, query, clipped)
        logger.info("knowledge.rerank.usage provider=bedrock reranker=%s documents=%d", self.spec.key, len(clipped))
        return sorted(scores, key=lambda score: (-score.relevance, score.index))


__all__ = ["BedrockReranker", "RerankScore"]
