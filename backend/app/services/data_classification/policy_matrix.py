"""The instance-wide classification policy matrix: what each data classification level allows.

The five levels are fixed (``DATA_CLASSIFICATION_ORDER``); their rules are configurable by platform admins.
Each rule is enforced at its existing decision point, never in a parallel path:

- ``seat_allowed`` and ``requires_governed_routing``: ``agent_gateway/seat_policy.seat_decision_for``;
- ``allowed_model_aliases``: the project model admission every gateway dispatch goes through
  (``model_gateway/litellm/project_admission.ProjectModelAdmission.decide``), so the inbound gateway, chat and
  the Knowledge model paths narrow alike. **Derived, read-only**: level L lists every enabled
  gateway model cleared at or above L in the Model catalog (``model_catalog/clearance``); a submitted or stored
  value is ignored;
- ``reranker_allowed``, ``remote_embeddings_allowed``: ``knowledge/embedding/selection.admit_remote``;
- ``connectors`` and ``log_masking_required``: the tool admission (``classification_tool_policy``);
- ``transcript_retention_days``: stored and shown only;
- ``device_runs_allowed``: the device dispatch gate (``devices/device_policy``); true at every level by
  default, protection comes from the model routing of each call of the device job.

Only rules that differ from the defaults are
stored, in the admin ``system_config`` store (:data:`POLICY_MATRIX_CONFIG_KEY`), so a missing row is the
default matrix. A stored value the backend cannot read is ``invalid`` and fails closed: every level gets
:data:`LOCKED_RULES`, never the permissive defaults.

The vocabulary and value types live in ``policy_rules``, the validation in ``policy_validation``; this module loads
the live matrix and keeps every name importable from here.
"""

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
    """The per-level gateway alias allowlists for the project model admission builders."""
    return (await load_classification_policy(db)).model_allowlists()


async def level_rules(db: AsyncSession, level: str) -> LevelRules:
    """The rules of one resolved level (for a decision point that holds a classification)."""
    return (await load_classification_policy(db)).rules_for(level)


def encoded_overrides(overrides: Mapping[str, Any], *, updated_by: str) -> str:
    return json.dumps({"overrides": overrides, "updated_by": updated_by}, sort_keys=True)


__all__ = [
    "encoded_overrides",
    "level_rules",
    "load_classification_policy",
    "model_allowlists",
]
