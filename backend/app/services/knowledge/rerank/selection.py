"""Which reranker an Instance uses (explicit setting, optional)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from ..embedding.port import EmbeddingError, EmbeddingState
from .bedrock import BedrockReranker
from .catalog import RerankerSpec, reranker_spec
from .client import build_reranker_client

RERANKER_ENV = "OCTRYX_KNOWLEDGE_RERANKER"


@dataclass(frozen=True, slots=True)
class RerankerRuntime:
    spec: RerankerSpec
    reranker: BedrockReranker


def reranker_from_environment(environ: Mapping[str, str] | None = None) -> RerankerRuntime:
    source = os.environ if environ is None else environ
    key = str(source.get(RERANKER_ENV) or "").strip()
    if not key:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "reranker_not_configured")
    try:
        spec = reranker_spec(key)
    except KeyError:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "reranker_unknown") from None
    # Its own fail-fast client (client.py), not the embedding client with its long timeouts and retries.
    client = build_reranker_client(reranker_region(source))
    return RerankerRuntime(spec=spec, reranker=BedrockReranker(spec, client=client))


def reranker_region(environ: Mapping[str, str]) -> str | None:
    region = str(environ.get("OCTRYX_KNOWLEDGE_EMBEDDING_REGION") or environ.get("AWS_REGION") or "").strip()
    return region or None


__all__ = ["RERANKER_ENV", "RerankerRuntime", "reranker_from_environment", "reranker_region"]
