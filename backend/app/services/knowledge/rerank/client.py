"""The reranker's own Bedrock client.

The shared embedding client (``embedding/bedrock.py``) waits up to 30 s per read and retries three times, which
suits bulk indexing. The reranker sits in front of every search, so it fails fast instead (2 s to connect, 8 s to
read, one attempt) and the search answers in fused order with ``rerank: unavailable``.
"""

from __future__ import annotations

from typing import Any

from ..embedding.bedrock import bedrock_runtime_hold, provider_failure
from ..embedding.port import EmbeddingError, EmbeddingState

RERANK_CONNECT_TIMEOUT_SECONDS = 2
RERANK_READ_TIMEOUT_SECONDS = 8
# botocore counts the first try: one attempt means no retry.
RERANK_MAX_ATTEMPTS = 1


def build_reranker_client(region: str | None) -> Any:
    """A ``bedrock-runtime`` client for reranking: short timeouts, no retries."""
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
