"""Project-scoped tool access policy helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..tools.definitions import get_tool_definition_metadata
from .tool_access_policy_config import _project_tool_visibility_policy, project_enforces_read_only_tools
from .tool_access_policy_rules import (
    HIGH_RISK_EXPLICIT_ALLOW_REASON,
    ToolProjectPolicyDecision,
    _decision,
    _explicit_allow_decision,
    _read_only_decision,
    _tool_requires_explicit_allow,
    _visibility_decision,
)
from .workflow_routing.tool_policy import tool_policy_has_rules


def tool_project_policy_decision(
    tool_name: str,
    project_config: dict[str, Any] | None,
) -> ToolProjectPolicyDecision:
    normalized_name = str(tool_name or "").strip()
    if not normalized_name:
        metadata = get_tool_definition_metadata(normalized_name)
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="tool_name",
            reason="empty_tool_name",
            metadata=metadata,
            error_message="Tool name is empty.",
        )

    metadata = get_tool_definition_metadata(normalized_name)
    requires_explicit_allow = _tool_requires_explicit_allow(metadata)
    if metadata.owner_type == "unknown" or metadata.risk == "unknown":
        return _decision(
            tool_name=normalized_name,
            allowed=False,
            policy="tool_governance_metadata",
            reason="unknown_tool_requires_metadata",
            metadata=metadata,
            error_message="Tool requires explicit governance metadata before execution.",
            requires_explicit_allow=True,
        )

    visibility_policy = _project_tool_visibility_policy(project_config)
    if tool_policy_has_rules(visibility_policy):
        return _visibility_decision(normalized_name, metadata, visibility_policy, requires_explicit_allow)
    if project_enforces_read_only_tools(project_config):
        return _read_only_decision(normalized_name, metadata, project_config, requires_explicit_allow)
    if requires_explicit_allow:
        return _explicit_allow_decision(normalized_name, metadata, project_config)

    return _decision(
        tool_name=normalized_name,
        allowed=True,
        policy="default_platform_policy",
        reason="allowed_by_default_platform_policy",
        metadata=metadata,
    )


def tool_is_allowed_by_project_policy(tool_name: str, project_config: dict[str, Any] | None) -> bool:
    return tool_project_policy_decision(tool_name, project_config).allowed


def explain_tool_project_policy_denial(tool_name: str, project_config: dict[str, Any] | None) -> str | None:
    decision = tool_project_policy_decision(tool_name, project_config)
    if decision.allowed:
        return None
    return decision.error_message or "Blocked by the project tool policy."


def filter_tool_definitions_for_project_policy(
    tool_definitions: list[dict[str, Any]],
    project_config: dict[str, Any] | None,
    *,
    confirmed_per_call: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    # Confirmed-per-call tools answer the high-risk explicit-allow rule exactly as dispatch does, so the offered tools
    # and dispatch agree.

    visibility_policy = _project_tool_visibility_policy(project_config)
    if not tool_policy_has_rules(visibility_policy) and not project_enforces_read_only_tools(project_config):
        return tool_definitions
    filtered: list[dict[str, Any]] = []
    for definition in tool_definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        tool_name = str((function or {}).get("name") or "").strip() if isinstance(function, dict) else ""
        decision = tool_project_policy_decision(tool_name, project_config)
        if decision.allowed or (
            decision.reason == HIGH_RISK_EXPLICIT_ALLOW_REASON
            and confirmed_per_call is not None
            and confirmed_per_call(tool_name)
        ):
            filtered.append(definition)
    return filtered


def blocked_tool_result(
    tool_name: str,
    decision: ToolProjectPolicyDecision | None = None,
) -> dict[str, Any]:
    resolved_decision = decision or tool_project_policy_decision(tool_name, {})
    return {
        "error": resolved_decision.error_message or "Tool is blocked by the project tool policy",
        "tool_name": str(tool_name or "").strip(),
        "policy": resolved_decision.policy,
        "policy_decision": resolved_decision.to_dict(),
    }


__all__ = [
    "blocked_tool_result",
    "explain_tool_project_policy_denial",
    "filter_tool_definitions_for_project_policy",
    "tool_project_policy_decision",
    "tool_is_allowed_by_project_policy",
]
