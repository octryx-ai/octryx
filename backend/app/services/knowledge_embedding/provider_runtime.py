"""Governed embedding runtime resolution via the control plane."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneRuntimeTarget, LLMProvider
from .drivers import FAMILY_BEDROCK, EmbeddingConfigurationError, expected_dimension
from .drivers.bedrock import BedrockEmbeddingDriver
from .providers import KnowledgeEmbeddingProvider, resolve_knowledge_embedding_provider

logger = logging.getLogger(__name__)

_EMBEDDING_USE_CASE_TAG = "embedding"


async def resolve_knowledge_embedding_runtime(db: AsyncSession) -> KnowledgeEmbeddingProvider:
    """Resolve the embedding provider, preferring the governed control-plane
    selection and falling back to the environment/local default."""
    governed = await _resolve_from_control_plane(db)
    if governed is not None:
        return governed
    return resolve_knowledge_embedding_provider()


async def _resolve_from_control_plane(db: AsyncSession) -> KnowledgeEmbeddingProvider | None:
    # Imported lazily: control_plane_service pulls a large dependency graph and
    # this module is imported from the embedding hot path.
    from ..control_plane_service import build_provider_client_kwargs_async

    # Read active runtime targets directly (no config creation / side effects, so
    # this is safe on the read/status paths and on a fresh DB).
    try:
        result = await db.execute(
            select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True))
        )
        targets = list(result.scalars().all())
    except Exception:  # control plane tables not present yet
        return None

    embedding_targets = [
        target
        for target in targets
        if _EMBEDDING_USE_CASE_TAG in {str(tag).strip().lower() for tag in target.use_case_tags}
    ]
    if not embedding_targets:
        return None
    embedding_targets.sort(key=lambda target: target.priority)

    for target in embedding_targets:
        provider_row = await db.get(LLMProvider, target.provider_id)
        if provider_row is None or not provider_row.is_active:
            logger.debug("Skipping embedding target with missing/inactive provider %s", target.provider_id)
            continue
        family = _embedding_family_for_provider(provider_row)
        if family == FAMILY_BEDROCK:
            client_kwargs = _bedrock_client_kwargs(await build_provider_client_kwargs_async(db, provider_row))
            model = str(target.model_id or "").strip()
            version = f"{FAMILY_BEDROCK}:{model}"
            driver = BedrockEmbeddingDriver(
                model=model,
                version=version,
                region=client_kwargs.get("region_name"),
                client_kwargs=client_kwargs,
            )
            return KnowledgeEmbeddingProvider(
                provider_id=FAMILY_BEDROCK,
                model=model,
                version=version,
                configured_provider=FAMILY_BEDROCK,
                configured_model=model,
                dimension=expected_dimension(FAMILY_BEDROCK, model),
                driver=driver,
            )
        raise EmbeddingConfigurationError(
            f"Provider '{provider_row.name}' (driver '{provider_row.driver}') is tagged for embeddings "
            f"but embedding is not supported for it yet. Use a Bedrock provider or the local in-process "
            f"embedding, or remove the '{_EMBEDDING_USE_CASE_TAG}' tag."
        )
    return None


def _embedding_family_for_provider(provider: LLMProvider) -> str | None:
    family = str(getattr(provider, "provider_family", "") or "").strip().lower()
    return FAMILY_BEDROCK if family == "aws" else None


def _bedrock_client_kwargs(provider_kwargs: dict[str, Any]) -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {}
    region = provider_kwargs.get("region")
    if region:
        client_kwargs["region_name"] = str(region)
    for key in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token"):
        value = provider_kwargs.get(key)
        if value:
            client_kwargs[key] = value
    return client_kwargs
