"""Validation of the Workspace's ``agent_gateway_policy`` before it is stored (``normalize_agent_gateway_policy``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..devices.device_runs_keys import DEVICE_RUNS_KEY, DeviceRunsPolicyError, normalize_device_runs
from .engine_keys import ENGINES_KEY, EnginePolicyError, normalize_engine_section
from .handoff_policy_keys import HANDOFF_POLICY_KEY, HandoffPolicyError, normalize_handoff_policy
from .policy_keys import (
    _BUDGET_KEYS,
    _PERMISSION_KEYS,
    _RULE_FIELDS,
    _TOP_LEVEL_KEYS,
    _VERIFICATION_KEYS,
    AGENT_GATEWAY_POLICY_CONFIG_KEY,
    BYPASS_KEY,
    BYPASS_MODES,
    FREE_SESSIONS_KEY,
    FREE_SESSIONS_MODES,
    MAX_DAILY_BUDGET_USD,
    MAX_LIST_ITEMS,
    MAX_RULE_ID_CHARS,
    MAX_RULES,
    MAX_TEXT_CHARS,
    MAX_TOKEN_CHARS,
    MAX_TOKENS,
    ROLE_MODE_CEILINGS,
    ROLE_MODE_ROLES,
    ROLE_MODES_KEY,
    RULE_KINDS,
    AgentGatewayPolicyError,
)
from .review_keys import REVIEW_KEY, ReviewPolicyError, normalize_review_section
from .sandbox_policy import SandboxPolicyError, normalize_sandbox
from .seat_policy_keys import SeatPolicyError, normalize_seat_policy
from .transcript_policy_keys import SESSION_TRANSCRIPTS_KEY, TranscriptPolicyError, normalize_transcript_policy


def _text(value: Any, path: str, *, limit: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise AgentGatewayPolicyError("invalid_text", path)
    return value.strip()


def _texts(value: Any, path: str, *, limit: int = MAX_LIST_ITEMS, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or len(value) > limit or (not value and not allow_empty):
        raise AgentGatewayPolicyError("invalid_list", path)
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _tokens(value: Any, path: str) -> list[str]:
    tokens = _texts(value, path, limit=MAX_TOKENS, allow_empty=False)
    if any(len(token) > MAX_TOKEN_CHARS or any(char.isspace() for char in token) for token in tokens):
        raise AgentGatewayPolicyError("invalid_token", path)
    return tokens


def _only_keys(value: Any, allowed: frozenset[str] | set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentGatewayPolicyError("not_an_object", path)
    unknown = set(value) - set(allowed)
    if unknown:
        raise AgentGatewayPolicyError("unknown_field", f"{path}.{sorted(unknown)[0]}")
    return value


def _normalize_rule(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentGatewayPolicyError("not_an_object", path)
    kind = value.get("kind")
    if kind not in RULE_KINDS:
        raise AgentGatewayPolicyError("unknown_rule_kind", f"{path}.kind")
    fields = _RULE_FIELDS[kind]
    rule = _only_keys(value, {"id", "kind", *fields}, path)
    missing = fields - set(rule)
    if missing:
        raise AgentGatewayPolicyError("missing_field", f"{path}.{sorted(missing)[0]}")
    normalized: dict[str, Any] = {"id": _text(rule.get("id"), f"{path}.id", limit=MAX_RULE_ID_CHARS), "kind": kind}
    if "prefix" in fields:
        normalized["prefix"] = _tokens(rule["prefix"], f"{path}.prefix")
    if "command" in fields:
        normalized["command"] = _tokens(rule["command"], f"{path}.command")
    if "argument" in fields:
        normalized["argument"] = _tokens([rule["argument"]], f"{path}.argument")[0]
    if "tools" in fields:
        normalized["tools"] = _texts(rule["tools"], f"{path}.tools", allow_empty=False)
    if "glob" in fields:
        normalized["glob"] = _text(rule["glob"], f"{path}.glob")
    return normalized


def _verification(value: Any) -> dict[str, Any]:
    path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.verification"
    verification = _only_keys(value, _VERIFICATION_KEYS, path)
    prefixes = verification.get("test_command_prefixes", [])
    if not isinstance(prefixes, list) or len(prefixes) > MAX_LIST_ITEMS:
        raise AgentGatewayPolicyError("invalid_list", f"{path}.test_command_prefixes")
    return {
        "test_command_prefixes": [
            _tokens(item, f"{path}.test_command_prefixes[{index}]") for index, item in enumerate(prefixes)
        ],
        "change_tools": _texts(verification.get("change_tools", []), f"{path}.change_tools"),
    }


def _tool_rules(rules: Any) -> list[dict[str, Any]]:
    path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.tool_rules"
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise AgentGatewayPolicyError("invalid_list", path)
    normalized_rules = [_normalize_rule(rule, f"{path}[{index}]") for index, rule in enumerate(rules)]
    if len({rule["id"] for rule in normalized_rules}) != len(normalized_rules):
        raise AgentGatewayPolicyError("duplicate_rule_id", path)
    return normalized_rules


def _client_permissions(value: Any) -> dict[str, Any]:
    path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.client_permissions"
    permissions = _only_keys(value, _PERMISSION_KEYS, path)
    return {
        "deny": _texts(permissions.get("deny", []), f"{path}.deny"),
        "ask": _texts(permissions.get("ask", []), f"{path}.ask"),
        **({"allow": _texts(permissions["allow"], f"{path}.allow")} if "allow" in permissions else {}),
    }


def _session_budget(value: Any) -> dict[str, Any]:
    path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.session_budget"
    budget = _only_keys(value, _BUDGET_KEYS, path)
    return {"per_user_daily_usd": _budget_amount(budget.get("per_user_daily_usd"), path)}


def _delegated(normalize: Callable[[Any, str], Any], value: Any, path: str, error_type: type[Exception]) -> Any:
    try:
        return normalize(value, path)
    except error_type as error:
        raise AgentGatewayPolicyError(error.reason, error.path) from None


def _session_modes(policy: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, allowed in ((FREE_SESSIONS_KEY, FREE_SESSIONS_MODES), (BYPASS_KEY, BYPASS_MODES)):
        if key in policy:
            if policy[key] not in allowed:
                raise AgentGatewayPolicyError("invalid_value", f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{key}")
            normalized[key] = policy[key]
    if ROLE_MODES_KEY in policy:
        modes = policy[ROLE_MODES_KEY]
        path = f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{ROLE_MODES_KEY}"
        if not isinstance(modes, dict) or any(role not in ROLE_MODE_ROLES for role in modes):
            raise AgentGatewayPolicyError("invalid_value", path)
        if any(value not in ROLE_MODE_CEILINGS for value in modes.values()):
            raise AgentGatewayPolicyError("invalid_value", path)
        normalized[ROLE_MODES_KEY] = dict(modes)
    return normalized


# Sections validated by their own modules, in this order after the session modes. REVIEW_KEY holds the independent
# reviewer's model and route per engine (``review_keys``).
_LATER_SECTIONS = (
    (DEVICE_RUNS_KEY, normalize_device_runs, DeviceRunsPolicyError),
    (ENGINES_KEY, normalize_engine_section, EnginePolicyError),
    (REVIEW_KEY, normalize_review_section, ReviewPolicyError),
    (SESSION_TRANSCRIPTS_KEY, normalize_transcript_policy, TranscriptPolicyError),
)


def normalize_agent_gateway_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    policy = _only_keys(value, _TOP_LEVEL_KEYS, AGENT_GATEWAY_POLICY_CONFIG_KEY)
    normalized: dict[str, Any] = {}
    if "verification" in policy:
        normalized["verification"] = _verification(policy["verification"])
    if "tool_rules" in policy:
        normalized["tool_rules"] = _tool_rules(policy["tool_rules"])
    if "client_permissions" in policy:
        normalized["client_permissions"] = _client_permissions(policy["client_permissions"])
    if "session_budget" in policy:
        normalized["session_budget"] = _session_budget(policy["session_budget"])
    if "sandbox" in policy:
        normalized["sandbox"] = _delegated(
            normalize_sandbox, policy["sandbox"], f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.sandbox", SandboxPolicyError)
    normalized.update(_delegated(normalize_seat_policy, policy, AGENT_GATEWAY_POLICY_CONFIG_KEY, SeatPolicyError))
    if HANDOFF_POLICY_KEY in policy:
        normalized[HANDOFF_POLICY_KEY] = _delegated(
            normalize_handoff_policy, policy[HANDOFF_POLICY_KEY],
            f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{HANDOFF_POLICY_KEY}", HandoffPolicyError)
    normalized.update(_session_modes(policy))
    for key, normalize, error_type in _LATER_SECTIONS:
        if key in policy:
            normalized[key] = _delegated(
                normalize, policy[key], f"{AGENT_GATEWAY_POLICY_CONFIG_KEY}.{key}", error_type)
    return normalized


def _budget_amount(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentGatewayPolicyError("invalid_budget", f"{path}.per_user_daily_usd")
    amount = float(value)
    if amount != amount or not 0 < amount <= MAX_DAILY_BUDGET_USD:
        raise AgentGatewayPolicyError("invalid_budget", f"{path}.per_user_daily_usd")
    return amount


__all__ = ["normalize_agent_gateway_policy"]
