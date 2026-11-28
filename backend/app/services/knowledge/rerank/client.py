"""The reranker's own Bedrock client. It fails fast: the reranker sits in front of every search."""

from __future__ import annotations

from typing import Any

from ..embedding.bedrock import bedrock_runtime_hold, provider_failure
from ..embedding.port import EmbeddingError, EmbeddingState

RERANK_CONNECT_TIMEOUT_SECONDS = 2
RERANK_READ_TIMEOUT_SECONDS = 8
# botocore counts the first try: one attempt means no retry.
RERANK_MAX_ATTEMPTS = 1


def build_reranker_client(region: str | None) -> Any:
    hold = bedrock_runtime_hold(region)
    if hold is not None:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, hold)
    import boto3
    from botocore.config import Config

    config = Config(
        region_name=region,
        connect_timeout=RERANK_CONNECT_TIMEOUT_SECONDS,
        read_timeout=RERANK_READ_TIMEOUT_SECONDS,
        retries={"max_attempts": RERANK_MAX_ATTEMPTS, "mode": "standard"},
    )
    try:
        return boto3.client("bedrock-runtime", config=config)
    except Exception as error:
        raise provider_failure(error) from None


__all__ = [
    "RERANK_CONNECT_TIMEOUT_SECONDS",
    "RERANK_MAX_ATTEMPTS",
    "RERANK_READ_TIMEOUT_SECONDS",
    "build_reranker_client",
]
