"""Which embedding space an Instance uses, and whether a Workspace may use it.

The space is an explicit operator setting per Instance, never inferred: without
``OCTRYX_KNOWLEDGE_EMBEDDING_SPACE`` the vector mode is ``needs_configuration``. Local spaces
keep text in-process, so every classification may use them. A remote space is admitted per
Workspace through the platform's data-policy gate (``model_gateway/data_policy``): the Workspace's
server-resolved classification must sit at or below the space's allowance, and an unresolved
classification is refused like at every other model boundary.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ...data_classification.workspace_overrides import workspace_rules_by_id
from ...model_gateway.data_policy.gate import data_policy_decision
from ...model_gateway.data_policy.source import resolve_workspace_data_classification
from ...policy_engine.points import POINT_REMOTE_MODEL, remote_query
from ...policy_engine.runtime import maintain_policy_runtime
from ...policy_engine.shadow import REASON_CEDAR_POLICY_DENIED, LegacyDecision, enforced_denial, shadow_decision
from .bedrock import BedrockEmbedder, build_bedrock_client
from .catalog import EmbeddingProvider, EmbeddingSpace, embedding_space
from .local import LocalEmbedder
from .port import Embedder, EmbeddingError, EmbeddingState

SPACE_ENV = "OCTRYX_KNOWLEDGE_EMBEDDING_SPACE"
MODEL_ROOT_ENV = "OCTRYX_KNOWLEDGE_EMBEDDING_MODEL_ROOT"
REGION_ENV = "OCTRYX_KNOWLEDGE_EMBEDDING_REGION"
DEFAULT_MODEL_ROOT = "/app/models/embedding"

REMOTE_KIND_EMBEDDINGS = "embeddings"
REMOTE_KIND_RERANKER = "reranker"
REASON_EMBEDDINGS_FORBIDDEN = "classification_policy_remote_embeddings_forbidden"
REASON_RERANKER_FORBIDDEN = "classification_policy_reranker_forbidden"
_MATRIX_RULES = {
    REMOTE_KIND_EMBEDDINGS: ("remote_embeddings_allowed", REASON_EMBEDDINGS_FORBIDDEN),
    REMOTE_KIND_RERANKER: ("reranker_allowed", REASON_RERANKER_FORBIDDEN),
}


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    space: EmbeddingSpace
    model_root: Path
    region: str | None


def embedding_config_from_environment(environ: Mapping[str, str] | None = None) -> EmbeddingConfig:
    """The Instance's embedding configuration; ``needs_configuration`` when no space is chosen."""
    source = os.environ if environ is None else environ
    key = str(source.get(SPACE_ENV) or "").strip()
    if not key:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "space_not_configured")
    try:
        space = embedding_space(key)
    except KeyError:
        raise EmbeddingError(EmbeddingState.NEEDS_CONFIGURATION, "space_unknown") from None
    region = str(source.get(REGION_ENV) or source.get("AWS_REGION") or source.get("AWS_DEFAULT_REGION") or "")
    return EmbeddingConfig(
        space=space,
        model_root=Path(str(source.get(MODEL_ROOT_ENV) or DEFAULT_MODEL_ROOT)),
        region=region.strip() or None,
    )


def build_embedder(config: EmbeddingConfig) -> Embedder:
    if config.space.provider is EmbeddingProvider.LOCAL:
        return LocalEmbedder(config.space, model_root=config.model_root)
    return BedrockEmbedder(config.space, client=build_bedrock_client(config.region))


async def admit_space(db: AsyncSession, *, project_id: str, space: EmbeddingSpace) -> None:
    """Refuse a remote space for a Workspace whose data may not reach that provider."""
    if space.provider is EmbeddingProvider.LOCAL:
        return
    await admit_remote(
        db, project_id=project_id, data_policy_class=space.data_policy_class, model_kind=REMOTE_KIND_EMBEDDINGS
    )


async def admit_remote(db: AsyncSession, *, project_id: str, data_policy_class: str | None, model_kind: str) -> None:
    """Refuse a remote model (embedding or rerank) above its approved data classification.

    The level's classification policy matrix rule (``reranker_allowed`` / ``remote_embeddings_allowed``)
    can only narrow what the data-policy gate admits; so can a Cedar denial in enforce mode.
    """
    rule = _MATRIX_RULES[model_kind]
    await maintain_policy_runtime()
    classification = await resolve_workspace_data_classification(db, project_id=project_id)
    decision = data_policy_decision(classification, data_policy_class)
    if not decision.allowed:
        _shadow(project_id, classification, data_policy_class, model_kind, None, False, decision.reason)
        # The gate's reasons are fixed codes; an unresolved classification is a missing setting.
        state = EmbeddingState.DENIED if classification.resolved else EmbeddingState.NEEDS_CONFIGURATION
        raise EmbeddingError(state, decision.reason)
    rules = await workspace_rules_by_id(db, project_id, classification.classification)  # stricter overrides
    allowed = bool(getattr(rules, rule[0]))
    comparison = _shadow(project_id, classification, data_policy_class, model_kind, rules, allowed,
                         "" if allowed else rule[1])
    if not allowed:
        raise EmbeddingError(EmbeddingState.DENIED, rule[1])
    if enforced_denial(allowed, comparison) is not None:
        raise EmbeddingError(EmbeddingState.DENIED, REASON_CEDAR_POLICY_DENIED)


def _shadow(project_id, classification, data_policy_class, model_kind, rules, allowed: bool, reason: str):
    """The Cedar policy engine's evaluation of the same question; in shadow mode only compared."""
    return shadow_decision(
        POINT_REMOTE_MODEL,
        LegacyDecision(allowed, reason),
        lambda: remote_query(project_id=project_id, classification=classification,
                             data_policy_class=data_policy_class, model_kind=model_kind, rules=rules),
    )


__all__ = [
    "DEFAULT_MODEL_ROOT",
    "REASON_EMBEDDINGS_FORBIDDEN",
    "REASON_RERANKER_FORBIDDEN",
    "REMOTE_KIND_EMBEDDINGS",
    "REMOTE_KIND_RERANKER",
    "MODEL_ROOT_ENV",
    "REGION_ENV",
    "SPACE_ENV",
    "EmbeddingConfig",
    "admit_remote",
    "admit_space",
    "build_embedder",
    "embedding_config_from_environment",
]
