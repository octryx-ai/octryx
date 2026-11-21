"""Read and write the classification policy matrix for the admin API.

The write path validates the whole submitted matrix (``policy_matrix.normalize_policy_levels``), stores only
the rules that differ from the defaults (no row at all when nothing differs) and writes one audit row with the
level/rule changes. Nothing here decides at runtime; the decision points read ``load_classification_policy``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER, classification_rank
from ..model_gateway.data_policy.effects import gateway_aliases
from ..system_config.values import set_system_config_value
from .levels import level_registry
from .policy_matrix import encoded_overrides, load_classification_policy
from .policy_rules import (
    CONNECTOR_ACCESS,
    CONNECTOR_FAMILIES,
    DERIVED_RULE_KEYS,
    POLICY_MATRIX_CONFIG_KEY,
    RULE_KEYS,
    ClassificationPolicy,
    default_rules,
)
from .policy_validation import normalize_policy_levels

POLICY_MATRIX_AUDIT_ACTION = "admin.data_classification.policy_updated"
_DESCRIPTION = "Classification policy matrix: rules per data classification level that differ from the defaults."


def _level_info(level: str) -> dict[str, Any]:
    """Label, colour, description and the model switch of a level."""
    found = level_registry().get(level)
    if found is None:
        return {}
    return {"label": found.label, "color": found.color, "description": found.description,
            "models_allowed": found.models_allowed, "builtin": found.builtin}


def policy_payload(policy: ClassificationPolicy, *, can_edit: bool, model_aliases: list[str]) -> dict[str, Any]:
    """The ``GET/PUT /api/v1/admin/data-classification/policy`` body."""
    return {
        "state": policy.state,
        "levels": [
            {"level": level, "rank": classification_rank(level), "rules": rules.to_dict(), **_level_info(level)}
            for level, rules in policy.levels().items()
        ],
        "defaults": {level: default_rules(level).to_dict() for level in DATA_CLASSIFICATION_ORDER},
        "rule_keys": list(RULE_KEYS),
        "connector_families": list(CONNECTOR_FAMILIES),
        "connector_access_values": list(CONNECTOR_ACCESS),
        "model_aliases": model_aliases,
        # Read-only rules derived from the Model catalog clearance (the editor links there).
        "derived_rules": sorted(DERIVED_RULE_KEYS),
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        "updated_by": policy.updated_by,
        "can_edit": can_edit,
    }


async def policy_view(db: AsyncSession, policy: ClassificationPolicy, *, can_edit: bool) -> dict[str, Any]:
    """The payload with ``model_aliases``: every alias of the active LiteLLM gateway providers, for the editor."""
    aliases = sorted({alias for alias, _allowance in await gateway_aliases(db)})
    return policy_payload(policy, can_edit=can_edit, model_aliases=aliases)


def _changes(before: ClassificationPolicy, after: ClassificationPolicy) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for level in DATA_CLASSIFICATION_ORDER:
        old, new = before.rules_for(level).to_dict(), after.rules_for(level).to_dict()
        changes.extend(
            {"level": level, "rule": key, "before": old[key], "after": new[key]}
            for key in RULE_KEYS
            if old[key] != new[key]
        )
    return changes


async def set_classification_policy(db: AsyncSession, *, levels: Any, actor_id: str) -> ClassificationPolicy:
    """Validate, store and audit a submitted matrix. Raises ``ClassificationPolicyError``; flushes, never commits."""
    overrides = normalize_policy_levels(levels)
    before = await load_classification_policy(db)
    await set_system_config_value(
        db,
        key=POLICY_MATRIX_CONFIG_KEY,
        value=encoded_overrides(overrides, updated_by=actor_id) if overrides else None,
        description=_DESCRIPTION,
        updated_by=actor_id,
        record_prompt_revision=False,
    )
    after = await load_classification_policy(db)
    db.add(
        AuditLog(
            user_id=actor_id,
            action=POLICY_MATRIX_AUDIT_ACTION,
            resource_type="system_config",
            resource_id=POLICY_MATRIX_CONFIG_KEY,
            details={"previous_state": before.state, "state": after.state, "changes": _changes(before, after)},
        )
    )
    await db.flush()
    return after


__all__ = ["POLICY_MATRIX_AUDIT_ACTION", "policy_payload", "policy_view", "set_classification_policy"]
