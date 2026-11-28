from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .drivers import (
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_IN_PROCESS_MODEL,
    FAMILY_BEDROCK,
    FAMILY_IN_PROCESS,
    FAMILY_LOCAL_HASH,
    BaseEmbeddingDriver,
    build_embedding_driver,
    expected_dimension,
    normalize_provider_id,
    resolve_driver_family,
)
from .scoring import DEFAULT_EMBEDDING_MODEL

KNOWLEDGE_EMBEDDING_PROVIDER_ENV = "OCTRYX_KNOWLEDGE_EMBEDDING_PROVIDER"
KNOWLEDGE_EMBEDDING_MODEL_ENV = "OCTRYX_KNOWLEDGE_EMBEDDING_MODEL"
DEFAULT_EMBEDDING_PROVIDER = FAMILY_LOCAL_HASH
DEFAULT_EMBEDDING_VERSION = "hash-v1"

_DEFAULT_MODEL_BY_FAMILY = {
    FAMILY_LOCAL_HASH: DEFAULT_EMBEDDING_MODEL,
    FAMILY_IN_PROCESS: DEFAULT_IN_PROCESS_MODEL,
    FAMILY_BEDROCK: DEFAULT_BEDROCK_MODEL,
}


def _version_for(family: str, model: str) -> str:
    if family == FAMILY_LOCAL_HASH:
        return DEFAULT_EMBEDDING_VERSION
    return f"{family}:{model}"


@dataclass(frozen=True)
class KnowledgeEmbeddingProvider:
    """Resolved embedding provider descriptor."""

    provider_id: str
    model: str
    version: str
    configured_provider: str
    configured_model: str
    configured_provider_available: bool = True
    fallback_reason: str | None = None
    dimension: int | None = None
    # A pre-built driver (e.g. Bedrock with per-provider credentials from the
    # control plane). When absent, the driver is built from the registry by
    # (provider_id, model, version). Excluded from equality/repr.
    driver: BaseEmbeddingDriver | None = field(default=None, compare=False, repr=False)

    def embed_text(self, text: str, *, is_query: bool = False) -> list[float]:
        return self.embed_texts([text], is_query=is_query)[0]

    def embed_texts(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        driver = self.driver or build_embedding_driver(self.provider_id, self.model, self.version)
        return driver.embed(list(texts), is_query=is_query)

    def metadata(self) -> dict[str, str | bool | int | None]:
        return {
            "embedding_provider": self.provider_id,
            "embedding_model": self.model,
            "embedding_version": self.version,
            "embedding_dimension": self.dimension,
            "configured_embedding_provider": self.configured_provider,
            "configured_embedding_model": self.configured_model,
            "provider_available": self.configured_provider_available,
            "provider_fallback_reason": self.fallback_reason,
        }


def resolve_knowledge_embedding_provider(
    *,
    provider_id: str | None = None,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> KnowledgeEmbeddingProvider:
    """Resolve the configured embedding provider/model into a descriptor."""
    source = os.environ if env is None else env
    settings_provider = settings_model = None
    if env is None and not provider_id:
        # .env-file friendly: pydantic settings hold values the process
        # environment does not export.
        from ...config import get_settings

        app_settings = get_settings()
        settings_provider = getattr(app_settings, "knowledge_embedding_provider", None)
        settings_model = getattr(app_settings, "knowledge_embedding_model", None)
    configured_provider = normalize_provider_id(
        provider_id
        or source.get(KNOWLEDGE_EMBEDDING_PROVIDER_ENV)
        or settings_provider
        or DEFAULT_EMBEDDING_PROVIDER
    )
    family = resolve_driver_family(configured_provider)

    if family == FAMILY_LOCAL_HASH:
        resolved_model = DEFAULT_EMBEDDING_MODEL
    else:
        incoming = str(model or "").strip()
        # A stale job/model carrying the hash model name must not pin a real
        # provider to the hash model; fall back to the configured/family default.
        if not incoming or incoming == DEFAULT_EMBEDDING_MODEL:
            incoming = str(source.get(KNOWLEDGE_EMBEDDING_MODEL_ENV) or settings_model or "").strip()
        resolved_model = incoming or _DEFAULT_MODEL_BY_FAMILY[family]

    version = _version_for(family, resolved_model)
    return KnowledgeEmbeddingProvider(
        provider_id=family,
        model=resolved_model,
        version=version,
        configured_provider=configured_provider,
        configured_model=resolved_model,
        configured_provider_available=True,
        fallback_reason=None,
        dimension=expected_dimension(family, resolved_model),
    )


__all__ = [
    "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_EMBEDDING_VERSION",
    "KNOWLEDGE_EMBEDDING_MODEL_ENV",
    "KNOWLEDGE_EMBEDDING_PROVIDER_ENV",
    "KnowledgeEmbeddingProvider",
    "resolve_knowledge_embedding_provider",
]
