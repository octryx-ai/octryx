"""Workflow routing tool-policy helpers."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from ...tools.tool_names import READONLY_TOOL_NAMES

READONLY_TOOL_NAME_VALUES = frozenset(str(name.value) for name in READONLY_TOOL_NAMES)


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw_item in value:
        item = str(raw_item or "").strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def normalized_tool_policy(tool_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = tool_policy if isinstance(tool_policy, dict) else {}
    return {
        "allowlist": list(dict.fromkeys(string_list(policy.get("allowlist")))),
        "denylist": list(dict.fromkeys(string_list(policy.get("denylist")))),
        "allow_patterns": string_list(policy.get("allow_patterns")),
        "deny_patterns": string_list(policy.get("deny_patterns")),
        "allow_read_only": bool(policy.get("allow_read_only", False)),
        # Explicit grants for high-risk tools (connector write/admin). Exact
        # names only — visibility rules (allowlist/patterns) do not double as
        # risk grants, otherwise a broad allow pattern silently unlocks every
        # high-risk tool.
        "high_risk_grants": list(dict.fromkeys(string_list(policy.get("high_risk_grants")))),
    }


def tool_policy_has_allow_rules(tool_policy: dict[str, Any] | None) -> bool:
    policy = normalized_tool_policy(tool_policy)
    return bool(policy["allowlist"] or policy["allow_patterns"] or policy["allow_read_only"])


def tool_policy_has_rules(tool_policy: dict[str, Any] | None) -> bool:
    policy = normalized_tool_policy(tool_policy)
    return bool(
        policy["allowlist"]
        or policy["denylist"]
        or policy["allow_patterns"]
        or policy["deny_patterns"]
        or policy["allow_read_only"]
    )


def tool_name_matches_any_pattern(tool_name: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(tool_name, pattern) for pattern in patterns)


def tool_name_is_allowed_by_policy(tool_name: str, tool_policy: dict[str, Any] | None) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    policy = normalized_tool_policy(tool_policy)
    allowed_by_rule = (
        name in set(policy["allowlist"])
        # A high-risk grant implies visibility; requiring the name in the
        # allowlist as well would be a silent second hurdle.
        or name in set(policy["high_risk_grants"])
        or tool_name_matches_any_pattern(name, policy["allow_patterns"])
        or (policy["allow_read_only"] and name in READONLY_TOOL_NAME_VALUES)
    )
    if tool_policy_has_allow_rules(policy) and not allowed_by_rule:
        return False
    if name in set(policy["denylist"]):
        return False
    if tool_name_matches_any_pattern(name, policy["deny_patterns"]):
        return False
    return True


def expand_tool_policy_allowlist(
    tool_policy: dict[str, Any] | None,
    *,
    available_tool_names: list[str],
    meta_tool_names: list[str] | None = None,
) -> list[str]:
    """Return concrete allowed tools in available-tool order."""

    ordered_names = [str(name or "").strip() for name in available_tool_names if str(name or "").strip()]
    meta_names = [str(name or "").strip() for name in (meta_tool_names or []) if str(name or "").strip()]
    if tool_policy_has_allow_rules(tool_policy):
        for name in meta_names:
            if name not in ordered_names:
                ordered_names.append(name)
    return [name for name in ordered_names if tool_name_is_allowed_by_policy(name, tool_policy)]
