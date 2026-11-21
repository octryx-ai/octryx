"""Validation of submitted and stored policy matrices; anything invalid raises or reads as ``invalid``."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..model_gateway.data_policy.classification import DATA_CLASSIFICATION_ORDER
from .policy_rules import (
    _ALIAS_PATTERN,
    _BOOL_RULES,
    CONNECTOR_ACCESS,
    CONNECTOR_FAMILIES,
    DERIVED_RULE_KEYS,
    ERROR_CONNECTOR_ACCESS_INVALID,
    ERROR_CONNECTOR_FAMILY_UNKNOWN,
    ERROR_LEVEL_DUPLICATE,
    ERROR_LEVEL_UNKNOWN,
    ERROR_LEVELS_INVALID,
    ERROR_RULE_INVALID,
    ERROR_RULE_UNKNOWN,
    ERROR_RULES_INVALID,
    MAX_ALIASES,
    MAX_RETENTION_DAYS,
    RULE_KEYS,
    STATE_CONFIGURED,
    STATE_DEFAULT,
    STATE_INVALID,
    ClassificationPolicyError,
    default_rules,
)


def _normalized_rule(key: str, value: Any, path: str) -> Any:
    if key in _BOOL_RULES:
        if type(value) is not bool:
            raise ClassificationPolicyError(ERROR_RULE_INVALID, path)
        return value
    if key == "allowed_model_aliases":
        if value is None:
            return None
        if not isinstance(value, list) or len(value) > MAX_ALIASES:
            raise ClassificationPolicyError(ERROR_RULE_INVALID, path)
        if not all(isinstance(item, str) and _ALIAS_PATTERN.match(item) for item in value):
            raise ClassificationPolicyError(ERROR_RULE_INVALID, path)
        return sorted(set(value))
    if key == "transcript_retention_days":
        if value is None:
            return None
        if type(value) is not int or not 1 <= value <= MAX_RETENTION_DAYS:
            raise ClassificationPolicyError(ERROR_RULE_INVALID, path)
        return value
    if not isinstance(value, Mapping):
        raise ClassificationPolicyError(ERROR_RULE_INVALID, path)
    connectors: dict[str, str] = {}
    for family, access in value.items():
        if family not in CONNECTOR_FAMILIES:
            raise ClassificationPolicyError(ERROR_CONNECTOR_FAMILY_UNKNOWN, f"{path}.{family}")
        if access not in CONNECTOR_ACCESS:
            raise ClassificationPolicyError(ERROR_CONNECTOR_ACCESS_INVALID, f"{path}.{family}")
        connectors[family] = access
    return connectors


def _overrides_for(level: str, rules: Any, path: str) -> dict[str, Any]:
    """The rules of one level that differ from its defaults; unknown or ill-typed rules raise."""
    if not isinstance(rules, Mapping):
        raise ClassificationPolicyError(ERROR_RULES_INVALID, path)
    default = default_rules(level).to_dict()
    overrides: dict[str, Any] = {}
    for key, value in rules.items():
        if key not in RULE_KEYS:
            raise ClassificationPolicyError(ERROR_RULE_UNKNOWN, f"{path}.{key}")
        if key in DERIVED_RULE_KEYS:
            continue
        normalized = _normalized_rule(key, value, f"{path}.{key}")
        if key == "connectors":
            changed = {family: access for family, access in normalized.items() if default[key][family] != access}
            if changed:
                overrides[key] = changed
        elif normalized != default[key]:
            overrides[key] = normalized
    return overrides


def normalize_policy_levels(levels: Any) -> dict[str, dict[str, Any]]:
    """``[{level, rules}]`` → the stored overrides ``{level: {rule: value}}``; raises ``ClassificationPolicyError``."""
    if not isinstance(levels, list):
        raise ClassificationPolicyError(ERROR_LEVELS_INVALID, "levels")
    overrides: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for index, item in enumerate(levels):
        path = f"levels[{index}]"
        if not isinstance(item, Mapping) or set(item) - {"level", "rules"}:
            raise ClassificationPolicyError(ERROR_LEVELS_INVALID, path)
        level = item.get("level")
        if level not in DATA_CLASSIFICATION_ORDER:
            raise ClassificationPolicyError(ERROR_LEVEL_UNKNOWN, f"{path}.level")
        if level in seen:
            raise ClassificationPolicyError(ERROR_LEVEL_DUPLICATE, f"{path}.level")
        seen.add(level)
        level_overrides = _overrides_for(level, item.get("rules", {}), f"{path}.rules")
        if level_overrides:
            overrides[level] = level_overrides
    return overrides


def _decoded(raw: str | None) -> tuple[str, dict[str, Any], str | None]:
    """``(state, overrides, updated_by)`` of a stored value; anything unreadable is ``invalid``."""
    if raw is None:
        return STATE_DEFAULT, {}, None
    try:
        stored = json.loads(raw)
        overrides = dict(stored["overrides"])
        listed = [{"level": level, "rules": rules} for level, rules in overrides.items()]
        normalized = normalize_policy_levels(listed)
    except (ValueError, KeyError, TypeError, AttributeError):
        return STATE_INVALID, {}, None
    if normalized != overrides:
        return STATE_INVALID, {}, None
    updated_by = stored.get("updated_by")
    return STATE_CONFIGURED, normalized, updated_by if isinstance(updated_by, str) else None
