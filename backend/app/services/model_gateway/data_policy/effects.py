"""What each data classification level admits in one Workspace, for the classification settings."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMProvider
from .classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    DATA_CLASSIFICATION_ORDER,
    WorkspaceDataClassification,
    classification_rank,
)
from .gate import data_policy_decision

# One plain-language sentence per level: the single source the settings UI shows. The backend
# has no translation hooks; the texts are English.
LEVEL_DESCRIPTIONS = {
    "public": "Public data; may be processed by any approved model.",
    "internal": "Company-internal data; may be processed by approved external models.",
    "confidential": "Confidential data; only models approved for confidential data, no personal subscription sessions.",
    "restricted": "Restricted data; only models explicitly approved for restricted data.",
    "secret": "Secret data; no external model is approved for it.",
}

REASON_RERANKER_NOT_CONFIGURED = "reranker_not_configured"
REASON_EMBEDDING_NOT_CONFIGURED = "embedding_space_not_configured"
REASON_EMBEDDING_LOCAL = "embedding_space_local"


def _level(value: str) -> WorkspaceDataClassification:
    return WorkspaceDataClassification(value, CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")


def _admits(level: str, allowance: str | None) -> tuple[bool, str]:
    decision = data_policy_decision(_level(level), allowance)
    return decision.allowed, "" if decision.allowed else decision.reason


# The runtime admission's precondition (rerank/admission_state): no key, an unknown key or the Bedrock hold is
# needs_configuration with its reason, never an allowed reranker.
def _reranker_class() -> tuple[str | None, str]:
    from ...knowledge.rerank.admission_state import STATE_OK, reranker_runtime_precondition

    precondition = reranker_runtime_precondition()
    if precondition["state"] != STATE_OK:
        return None, str(precondition["hold_reason"] or REASON_RERANKER_NOT_CONFIGURED)
    return precondition["data_policy_class"], ""


def _embedding_space() -> tuple[str | None, str]:
    from ...knowledge.embedding.catalog import EmbeddingProvider
    from ...knowledge.embedding.port import EmbeddingError
    from ...knowledge.embedding.selection import embedding_config_from_environment

    try:
        space = embedding_config_from_environment(os.environ).space
    except EmbeddingError:
        return None, REASON_EMBEDDING_NOT_CONFIGURED
    if space.provider is EmbeddingProvider.LOCAL:
        return None, REASON_EMBEDDING_LOCAL
    return space.data_policy_class, ""


async def gateway_aliases(db: AsyncSession) -> list[tuple[str, str]]:
    from ..litellm.alias_catalog import admitted_alias_entries
    from ..litellm.runtime_admission import LITELLM_GATEWAY_DRIVER

    rows = (
        await db.execute(
            select(LLMProvider.config_json).where(
                LLMProvider.is_active.is_(True), LLMProvider.driver == LITELLM_GATEWAY_DRIVER
            )
        )
    ).scalars()
    entries = {(entry.alias, entry.data_policy_class) for config in rows for entry in admitted_alias_entries(config)}
    return sorted(entries)


def _remote_model(level: str, allowance: str | None, hold: str, matrix_allows: bool, denial: str) -> tuple[bool, str]:
    if not allowance:
        return False, hold
    admitted, reason = _admits(level, allowance)
    if admitted and not matrix_allows:
        return False, denial
    return admitted, reason


async def classification_effects(db: AsyncSession, *, workspace_id: str) -> list[dict[str, Any]]:
    from ...agent_gateway.policy import load_workspace_policy
    from ...agent_gateway.seat_policy import seat_decision_for
    from ...data_classification.policy_matrix import load_classification_policy
    from ...knowledge.embedding.selection import REASON_EMBEDDINGS_FORBIDDEN, REASON_RERANKER_FORBIDDEN

    reranker_class, reranker_reason = _reranker_class()
    embedding_class, embedding_reason = _embedding_space()
    aliases = await gateway_aliases(db)
    policy = (await load_workspace_policy(db, workspace_id)).policy
    matrix = await load_classification_policy(db)
    levels = []
    for value in DATA_CLASSIFICATION_ORDER:
        rules = matrix.rules_for(value)
        reasons: dict[str, str] = {}
        reranker, reason = _remote_model(
            value, reranker_class, reranker_reason, rules.reranker_allowed, REASON_RERANKER_FORBIDDEN
        )
        if not reranker:
            reasons["reranker_allowed"] = reason
        reranker_state = "ok" if reranker else ("denied" if reranker_class else "needs_configuration")
        if embedding_class:
            embeddings, reason = _remote_model(
                value, embedding_class, embedding_reason, rules.remote_embeddings_allowed,
                REASON_EMBEDDINGS_FORBIDDEN,
            )
        else:
            embeddings, reason = embedding_reason == REASON_EMBEDDING_LOCAL, embedding_reason
        if reason:
            reasons["remote_embeddings_allowed"] = reason
        seat = (
            seat_decision_for(policy, rules, workspace_id=workspace_id, level=value) if policy is not None else None
        )
        if seat is None or not seat.allowed:
            reasons["seat_mode_allowed"] = seat.reason if seat is not None else "policy_invalid"
        levels.append(
            {
                "value": value,
                "rank": classification_rank(value),
                "description": LEVEL_DESCRIPTIONS.get(value, ""),
                "rules": rules.to_dict(),
                "effects": {
                    "reranker_allowed": reranker,
                    "reranker_state": reranker_state,
                    "remote_embeddings_allowed": embeddings,
                    "seat_mode_allowed": bool(seat and seat.allowed),
                    "governed_models": [
                        alias
                        for alias, allowance in aliases
                        if _admits(value, allowance)[0]
                        and (rules.allowed_model_aliases is None or alias in rules.allowed_model_aliases)
                    ],
                    "connectors": rules.to_dict()["connectors"],
                    "log_masking_required": rules.log_masking_required,
                    "reasons": reasons,
                },
            }
        )
    return levels


__all__ = [
    "LEVEL_DESCRIPTIONS",
    "REASON_EMBEDDING_LOCAL",
    "REASON_EMBEDDING_NOT_CONFIGURED",
    "REASON_RERANKER_NOT_CONFIGURED",
    "classification_effects",
    "gateway_aliases",
]
