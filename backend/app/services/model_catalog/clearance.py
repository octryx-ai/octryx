"""Data clearance on the model: "cleared up to <level>", and the per-level model lists derived from it."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER, classification_rank
from ..model_gateway.litellm.alias_catalog import DATA_POLICY_CLASSES, admitted_alias_entries

GATEWAY_DRIVER = "litellm_gateway"
CLEARANCE_LEVELS: tuple[str, ...] = tuple(level for level in DATA_CLASSIFICATION_ORDER if level in DATA_POLICY_CLASSES)

ERROR_CLEARANCE_INVALID = "model_catalog_clearance_invalid"


def normalized_clearance(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    level = str(value).strip().lower()
    if level not in CLEARANCE_LEVELS:
        raise ValueError(ERROR_CLEARANCE_INVALID)
    return level


def cleared_for(cleared_up_to: Any, level: str) -> bool:
    cleared, wanted = classification_rank(cleared_up_to), classification_rank(level)
    return cleared is not None and wanted is not None and cleared >= wanted


def _rank(level: Any) -> int:
    rank = classification_rank(level) if level else None
    return -1 if rank is None else rank


def is_raise(before: Any, after: Any) -> bool:
    return _rank(after) > _rank(before)


async def cleared_aliases_by_level(db: AsyncSession) -> dict[str, tuple[str, ...]]:
    providers = (
        await db.execute(
            select(LLMProvider.id, LLMProvider.config_json).where(
                LLMProvider.is_active.is_(True), LLMProvider.driver == GATEWAY_DRIVER
            )
        )
    ).all()
    if not providers:
        # No gateway connection: there is no catalog model to derive from, and a gateway dispatch is still bound
        # by the alias' own data-policy gate. No level narrows (an empty mapping), rather than "none allowed".
        return {}
    rows = {
        (provider_id, model_id): (is_active, cleared)
        for provider_id, model_id, is_active, cleared in (
            await db.execute(
                select(LLMModel.provider_id, LLMModel.model_id, LLMModel.is_active, LLMModel.cleared_up_to).where(
                    LLMModel.provider_id.in_([provider_id for provider_id, _config in providers])
                )
            )
        ).all()
    }
    clearance: dict[str, str | None] = {}
    for provider_id, config in providers:
        for entry in admitted_alias_entries(config):
            row = rows.get((provider_id, entry.alias))
            if row is None:
                level = entry.data_policy_class
            else:
                level = row[1] if row[0] else None
            # The same alias on two gateway providers: the more permissive row wins (either can serve it).
            if entry.alias not in clearance or _rank(level) > _rank(clearance[entry.alias]):
                clearance[entry.alias] = level
    return {
        level: tuple(sorted(alias for alias, cleared in clearance.items() if cleared_for(cleared, level)))
        for level in DATA_CLASSIFICATION_ORDER
    }


__all__ = [
    "CLEARANCE_LEVELS",
    "ERROR_CLEARANCE_INVALID",
    "GATEWAY_DRIVER",
    "cleared_aliases_by_level",
    "cleared_for",
    "is_raise",
    "normalized_clearance",
]
