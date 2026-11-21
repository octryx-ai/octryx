"""AWS Bedrock embeddings (Titan Text v2, Cohere Embed Multilingual v3).

The caller admits the Workspace first (``selection.admit_space``); this adapter only talks to the
provider. Credentials come from the ambient AWS chain and never pass through here. Every failure is
reduced to a fixed state and reason: provider messages, request bodies and identities are dropped.
Usage is logged as counts only (texts, provider-reported input tokens), never content.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from typing import Any

from .catalog import EmbeddingProvider, EmbeddingSpace
from .port import EmbeddingError, EmbeddingPurpose, EmbeddingState, checked_inputs, checked_vectors

logger = logging.getLogger(__name__)

TITAN_MODEL_PREFIX = "amazon.titan-embed-text-v2"
COHERE_MODEL_PREFIX = "cohere.embed-multilingual-v3"
COHERE_MAX_TEXTS = 96
_READ_TIMEOUT_SECONDS = 30
_CONNECT_TIMEOUT_SECONDS = 5

_DENIED_CODES = frozenset({"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"})
_UNAVAILABLE_CODES = frozenset(
    {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException", "InternalServerException"}
)
_NOT_CONFIGURED_CODES = frozenset({"ResourceNotFoundException"})


def provider_failure(error: Exception) -> EmbeddingError:
    """Map a provider exception to a closed state; the exception text is never read."""
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = str((response.get("Error") or {}).get("Code") or "")
    name = type(error).__name__
    if code in _DENIED_CODES:
        return EmbeddingError(EmbeddingState.DENIED, "provider_access_denied")
    if code in _UNAVAILABLE_CODES:
        return EmbeddingError(EmbeddingState.UNAVAILABLE, "provider_unavailable")
    if code in _NOT_CONFIGURED_CODES:
        return EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "model_not_available")
    if code == "ValidationException":
        return EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_rejected_request")
    if name in {"NoCredentialsError", "PartialCredentialsError", "ProfileNotFound", "NoRegionError"}:
        return EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "credentials_missing")
    return EmbeddingError(EmbeddingState.UNAVAILABLE, "provider_failed")


def bedrock_runtime_hold(region: str | None) -> str | None:
    """Why no ``bedrock-runtime`` client can be built here (``runtime_missing``, ``region_missing``), or ``None``.

    The one availability check for building the client and for reporting it (Knowledge settings).
    """
    if importlib.util.find_spec("boto3") is None or importlib.util.find_spec("botocore") is None:
        return "runtime_missing"
    if not region:
        return "region_missing"
    return None


def build_bedrock_client(region: str | None) -> Any:
    """A ``bedrock-runtime`` client with bounded timeouts and standard retries."""
    hold = bedrock_runtime_hold(region)
    if hold is not None:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, hold)
    import boto3
    from botocore.config import Config

    config = Config(
        region_name=region,
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        read_timeout=_READ_TIMEOUT_SECONDS,
        retries={"max_attempts": 3, "mode": "standard"},
    )
    try:
        return boto3.client("bedrock-runtime", config=config)
    except Exception as error:
        raise provider_failure(error) from None


class BedrockEmbedder:
    """``Embedder`` for a Bedrock space. ``client`` is a ``bedrock-runtime`` client."""

    def __init__(self, space: EmbeddingSpace, *, client: Any) -> None:
        if space.provider is not EmbeddingProvider.BEDROCK:
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider")
        if not space.model.startswith((TITAN_MODEL_PREFIX, COHERE_MODEL_PREFIX)):
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "model_family")
        self.space = space
        self._client = client

    def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.invoke_model(
                modelId=self.space.model,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            payload = json.loads(response["body"].read())
        except EmbeddingError:
            raise
        except Exception as error:
            raise provider_failure(error) from None
        if type(payload) is not dict:
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
        return payload

    def _titan(self, texts: list[str]) -> tuple[list[Any], int]:
        vectors, tokens = [], 0
        for text in texts:
            payload = self._invoke({"inputText": text, "dimensions": self.space.dimensions, "normalize": True})
            vectors.append(payload.get("embedding"))
            count = payload.get("inputTextTokenCount")
            tokens += count if type(count) is int else 0
        return vectors, tokens

    def _cohere(self, texts: list[str], purpose: EmbeddingPurpose) -> tuple[list[Any], int]:
        input_type = "search_query" if purpose is EmbeddingPurpose.QUERY else "search_document"
        vectors: list[Any] = []
        for start in range(0, len(texts), COHERE_MAX_TEXTS):
            batch = texts[start : start + COHERE_MAX_TEXTS]
            payload = self._invoke(
                {"texts": batch, "input_type": input_type, "truncate": "END", "embedding_types": ["float"]}
            )
            embeddings = payload.get("embeddings")
            floats = embeddings.get("float") if isinstance(embeddings, dict) else None
            if type(floats) is not list:
                raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "provider_response")
            vectors.extend(floats)
        # Cohere on Bedrock reports no token count in the body; the text count is the usage evidence.
        return vectors, 0

    async def embed(self, texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]:
        prepared = checked_inputs(self.space, texts, purpose)
        if self.space.model.startswith(TITAN_MODEL_PREFIX):
            raw, tokens = await asyncio.to_thread(self._titan, prepared)
        else:
            raw, tokens = await asyncio.to_thread(self._cohere, prepared, purpose)
        vectors = checked_vectors(self.space, raw, len(prepared))
        logger.info(
            "knowledge.embedding.usage provider=bedrock space=%s purpose=%s texts=%d input_tokens=%d",
            self.space.key,
            purpose.value,
            len(prepared),
            tokens,
        )
        return vectors


__all__ = ["BedrockEmbedder", "build_bedrock_client", "provider_failure"]
