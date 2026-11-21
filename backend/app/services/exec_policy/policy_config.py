"""Exec Policy config values: the defaults, the allow-list merge rules and normalization of a stored config."""

from __future__ import annotations

import copy
from typing import Any

from .guard_rules import (
    AGENT_GUARD_RULES_KEY,
    CUSTOM_TOOL_GUARD_RULES_KEY,
    default_agent_guard_rules,
    normalize_agent_guard_rules,
    normalize_custom_tool_guard_rules,
)

DEFAULT_EXEC_POLICY_CONFIG: dict[str, Any] = {
    # ── Shell Execution Security ──
    "always_deny_patterns": [
        r"\brm\s+-rf\s+/(?:\s|$)",
        r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b",
        r"\bdd\s+if=",
        # As a command (at the start, after ; & | ( or sudo), not a word in code, so
        # ``python -c "... server.shutdown()"`` is not refused as destructive.
        r"(?:^|[;&|(\n]\s*|\bsudo\s+)shutdown\b",
        r"(?:^|[;&|(\n]\s*|\bsudo\s+)reboot\b",
        r"(?:^|[;&|(\n]\s*|\bsudo\s+)poweroff\b",
        r":\(\)\s*\{\s*:\|:&\s*\};:",
    ],
    "diagnosis_read_only_commands": [
        "cat",
        "cd",
        "date",
        "echo",
        "env",
        "find",
        "grep",
        "head",
        "id",
        "ls",
        "pwd",
        "printenv",
        "rg",
        "sed",
        "sort",
        "tail",
        "uniq",
        "wc",
        "whoami",
    ],
    "diagnosis_git_subcommands": [
        "branch",
        "diff",
        "log",
        "remote",
        "rev-parse",
        "show",
        "status",
    ],
    "diagnosis_kubectl_verbs": [
        "api-resources",
        "api-versions",
        "auth",
        "cluster-info",
        "describe",
        "events",
        "explain",
        "get",
        "logs",
        "top",
        "version",
    ],
    "shell_risk_operators": ["&&", "||", ";", ">", ">>", "| tee", "tee "],
    # ── Agent Guard Policies ──
    AGENT_GUARD_RULES_KEY: default_agent_guard_rules(),
    CUSTOM_TOOL_GUARD_RULES_KEY: [],
}

# The allow lists that grow with the platform's defaults (defaults must work). A stored list never
# hides a default added later: the effective list is the stored list plus every current default the admin did not
# explicitly remove (``<key>_removed_defaults``). Otherwise a stored full copy of an old list keeps
# new read-only defaults (such as ``cd`` and ``grep``) from every phase until an admin edits it.
DEFAULT_ALLOW_KEYS = ("diagnosis_read_only_commands", "diagnosis_git_subcommands", "diagnosis_kubectl_verbs")
REMOVED_SUFFIX = "_removed_defaults"
def removed_key(key: str) -> str:
    return f"{key}{REMOVED_SUFFIX}"


def _clean(values: Any) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip())) if isinstance(
        values, list) else []


def removed_defaults(key: str, stored: list[str]) -> list[str]:
    """The current defaults a saved list leaves out: what an admin removed on purpose."""
    return [item for item in DEFAULT_EXEC_POLICY_CONFIG[key] if item not in stored]


def merged_allow_list(key: str, stored: list[str], removed: list[str]) -> list[str]:
    """The stored list in its own order, then every current default it lacks that was not removed."""
    return [*stored, *(item for item in DEFAULT_EXEC_POLICY_CONFIG[key] if item not in stored and item not in removed)]


def _allow_list(key: str, source: dict[str, Any]) -> tuple[list[str], list[str]] | None:
    """``(effective list, removed defaults)`` of a stored allow list, or ``None`` when the row does not set it."""
    if not isinstance(source.get(key), list):
        return None
    stored = _clean(source[key])
    raw_removed = source.get(removed_key(key))
    if isinstance(raw_removed, list):
        removed = _clean(raw_removed)
    else:  # a stored list without its removals (the shipped defaults): defaults it lacks count as removed
        removed = removed_defaults(key, stored)
    return merged_allow_list(key, stored, removed), removed


def with_removed_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """A config to store: each allow list it sets also names the defaults it leaves out (explicit removals)."""
    stored = dict(config)
    for key in DEFAULT_ALLOW_KEYS:
        if isinstance(stored.get(key), list):
            stored[removed_key(key)] = removed_defaults(key, _clean(stored[key]))
    return stored


# Keys whose values are lists of strings (used by normalize)
_LIST_KEYS = [
    "always_deny_patterns",
    "diagnosis_read_only_commands",
    "diagnosis_git_subcommands",
    "diagnosis_kubectl_verbs",
    "shell_risk_operators",
]

# The fields nothing enforced are not part of the policy (tool, model, session, audit, domain, agent-type, output and
# schedule limits): a stored value is dropped on the next normalization.
_INT_KEYS: list[str] = []
_STR_KEYS: list[str] = []


def _copy_default_exec_policy_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_EXEC_POLICY_CONFIG)


def _normalized_exec_policy_base(base_config: dict[str, Any] | None) -> dict[str, Any]:
    if base_config is None:
        return _copy_default_exec_policy_config()
    return normalize_exec_policy_config(base_config, base_config=None)


def normalize_exec_policy_config(
    raw: dict[str, Any] | None,
    *,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _normalized_exec_policy_base(base_config)
    source = raw or {}
    # List fields
    for key in _LIST_KEYS:
        value = source.get(key)
        if not isinstance(value, list):
            continue
        payload[key] = [str(item).strip() for item in value if str(item).strip()]
    for key in DEFAULT_ALLOW_KEYS:
        allow = _allow_list(key, source)
        if allow is not None:
            payload[key], payload[removed_key(key)] = allow
        else:
            payload.setdefault(removed_key(key), [])
    # Integer fields
    for key in _INT_KEYS:
        value = source.get(key)
        if value is not None:
            try:
                payload[key] = max(0, int(value))
            except (ValueError, TypeError):
                pass
    # String fields
    for key in _STR_KEYS:
        value = source.get(key)
        if value is not None:
            payload[key] = str(value).strip()
    raw_guard_rules = source.get(AGENT_GUARD_RULES_KEY, payload.get(AGENT_GUARD_RULES_KEY))
    payload[AGENT_GUARD_RULES_KEY] = normalize_agent_guard_rules(raw_guard_rules)
    raw_custom_tool_guard_rules = source.get(
        CUSTOM_TOOL_GUARD_RULES_KEY,
        payload.get(CUSTOM_TOOL_GUARD_RULES_KEY),
    )
    payload[CUSTOM_TOOL_GUARD_RULES_KEY] = normalize_custom_tool_guard_rules(raw_custom_tool_guard_rules)
    return payload
