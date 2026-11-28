"""The instance-wide classification policy matrix: what each data classification level allows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SystemConfig
from .policy_rules import DEFAULT_POLICY, POLICY_MATRIX_CONFIG_KEY, ClassificationPolicy, LevelRules
from .policy_validation import _decoded


async def load_classification_policy(db: AsyncSession) -> ClassificationPolicy:
    from .candidate import current_candidate

    candidate = current_candidate()  # a draft under preview; never set for live traffic
    if candidate is not None:
        return candidate
    from .levels import ensure_level_registry

    await ensure_level_registry(db)  # levels added by another worker's publish
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.key == POLICY_MATRIX_CONFIG_KEY))
    ).scalar_one_or_none()
    from ..model_catalog.clearance import cleared_aliases_by_level

    derived = await cleared_aliases_by_level(db)
    if row is None or not str(row.value or "").strip():
        return replace(DEFAULT_POLICY, derived_model_aliases=derived)
    state, overrides, updated_by = _decoded(str(row.value))
    return ClassificationPolicy(state=state, overrides=overrides, updated_at=row.updated_at, updated_by=updated_by,
                                derived_model_aliases=derived)


async def model_allowlists(db: AsyncSession) -> dict[str, frozenset[str]]:
    return (await load_classification_policy(db)).model_allowlists()


async def level_rules(db: AsyncSession, level: str) -> LevelRules:
    return (await load_classification_policy(db)).rules_for(level)


def encoded_overrides(overrides: Mapping[str, Any], *, updated_by: str) -> str:
    return json.dumps({"overrides": overrides, "updated_by": updated_by}, sort_keys=True)


__all__ = [
    "encoded_overrides",
    "level_rules",
    "load_classification_policy",
    "model_allowlists",
]
