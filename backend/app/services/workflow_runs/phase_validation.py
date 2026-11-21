"""Validation of one phase definition of a phased workflow: shape, checks, steps, tools, safety, capability.

The phased designer validates every phase on preview and save, and graph validation refuses a phase
with errors (``graph_node_rules``).
"""

from __future__ import annotations

from typing import Any

from ..policy_lists.model_capabilities import required_model_capability_errors
from ..run_capability.definition_contract import validate_definition_capability_class
from ..safety_gate import MUTATING_TOOL_NAMES
from ..workflow_checks.library import validate_checks
from ..workflow_checks.steps import validate_steps
from ..workflow_routing.tool_policy import (
    normalized_tool_policy,
    tool_name_is_allowed_by_policy,
    tool_name_matches_any_pattern,
    tool_policy_has_allow_rules,
)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def validate_phase_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """``{"valid", "errors", "warnings"}`` of one phase's ``workflow_id``/``workflow_class``, contract, tool
    policy and safety constraints."""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    workflow_contract = payload.get("workflow_contract")
    tool_policy = payload.get("tool_policy") or {}
    safety_constraints = payload.get("safety_constraints") or {}
    if not str(payload.get("workflow_id") or "").strip():
        errors.append({"code": "missing_workflow_id", "message": "workflow_id is required"})
    if not str(payload.get("workflow_class") or "").strip():
        errors.append({"code": "missing_workflow_class", "message": "workflow_class is required"})
    if isinstance(workflow_contract, dict) and not str(workflow_contract.get("when_to_use") or "").strip():
        warnings.append({"code": "definition_missing_when_to_use",
                         "message": "The phase has no workflow_contract.when_to_use one-liner."})
    _check_contract_sections(workflow_contract, tool_policy, safety_constraints, errors=errors)
    policy = normalized_tool_policy(tool_policy if isinstance(tool_policy, dict) else {})
    errors.extend(_unsafe_mutating_tool_errors(policy, safety_constraints))
    capability_errors, capability_warnings = validate_definition_capability_class(
        is_definition=True,
        workflow_contract=workflow_contract,
        tool_policy=tool_policy,
        safety_constraints=safety_constraints,
    )
    errors.extend(capability_errors)
    errors.extend(required_model_capability_errors(workflow_contract))
    warnings.extend(capability_warnings)
    _check_tool_policy_rules(policy, errors=errors, warnings=warnings)
    warnings.extend(
        _validate_workflow_contract_tool_coverage(
            workflow_contract=workflow_contract if isinstance(workflow_contract, dict) else {},
            tool_policy=tool_policy if isinstance(tool_policy, dict) else {},
        )
    )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def _check_contract_sections(
    workflow_contract: Any, tool_policy: Any, safety_constraints: Any, *, errors: list[dict[str, str]]
) -> None:
    if not isinstance(workflow_contract, dict):
        errors.append({"code": "invalid_workflow_contract", "message": "workflow_contract must be an object"})
    errors.extend(validate_checks(workflow_contract.get("checks") if isinstance(workflow_contract, dict) else None))
    errors.extend(validate_steps(workflow_contract))
    if not isinstance(tool_policy, dict):
        errors.append({"code": "invalid_tool_policy", "message": "tool_policy must be an object"})
    if not isinstance(safety_constraints, dict):
        errors.append({"code": "invalid_safety_constraints", "message": "safety_constraints must be an object"})
    if isinstance(tool_policy, dict):
        errors.extend(_validate_tool_policy_shape(tool_policy))


def _mutating_tools_allowed(policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The mutating tools a normalized tool policy allows: by name, and by an allow pattern no deny rule covers."""
    denylist = set(policy["denylist"])
    mutating_allowed = sorted(set(policy["allowlist"]).intersection(MUTATING_TOOL_NAMES))
    mutating_allowed_by_pattern = sorted(
        tool_name
        for tool_name in MUTATING_TOOL_NAMES
        if tool_name_matches_any_pattern(tool_name, policy["allow_patterns"])
        and tool_name not in denylist
        and not tool_name_matches_any_pattern(tool_name, policy["deny_patterns"])
    )
    return mutating_allowed, mutating_allowed_by_pattern


def _unsafe_mutating_tool_errors(policy: dict[str, Any], safety_constraints: Any) -> list[dict[str, str]]:
    mutating_allowed, mutating_allowed_by_pattern = _mutating_tools_allowed(policy)
    diagnosis_mode = bool((safety_constraints or {}).get("diagnosis_mode", False))
    allow_mutating = bool((safety_constraints or {}).get("allow_mutating_tools", False))
    if diagnosis_mode and (mutating_allowed or mutating_allowed_by_pattern) and not allow_mutating:
        unsafe_tools = sorted(set(mutating_allowed).union(mutating_allowed_by_pattern))
        return [
            {
                "code": "unsafe_mutating_tools",
                "message": f"A diagnosis-mode phase cannot allow mutating tools: {', '.join(unsafe_tools)}",
            }
        ]
    return []


def _check_tool_policy_rules(
    policy: dict[str, Any], *, errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> None:
    if set(policy["allowlist"]).intersection(set(policy["denylist"])):
        errors.append({"code": "allowlist_denylist_overlap", "message": "tool allowlist and denylist overlap"})
    if set(policy["allow_patterns"]).intersection(policy["deny_patterns"]):
        errors.append({"code": "allow_pattern_deny_pattern_overlap", "message": "tool allow and deny patterns overlap"})
    if not tool_policy_has_allow_rules(policy):
        warnings.append({"code": "empty_tool_allowlist", "message": "No explicit tool allow rule configured"})


def _validate_workflow_contract_tool_coverage(
    *,
    workflow_contract: dict[str, Any],
    tool_policy: dict[str, Any],
) -> list[dict[str, str]]:
    required_tools = _workflow_contract_required_tools(workflow_contract)
    if not required_tools or not tool_policy_has_allow_rules(tool_policy):
        return []

    missing_tools = [
        tool_name
        for tool_name in required_tools
        if not tool_name_is_allowed_by_policy(tool_name, tool_policy)
    ]
    if not missing_tools:
        return []
    return [
        {
            "code": "workflow_contract_tools_not_allowed",
            "message": (
                "workflow_contract tools contain entries that are not allowed by tool_policy: "
                f"{', '.join(missing_tools)}"
            ),
        }
    ]


def _workflow_contract_required_tools(workflow_contract: dict[str, Any]) -> list[str]:
    tools = _string_list(workflow_contract.get("allowed_tools"))
    raw_steps = workflow_contract.get("source_steps")
    if isinstance(raw_steps, list):
        tools.extend(
            str((step or {}).get("tool") or (step or {}).get("tool_name") or "").strip()
            for step in raw_steps
            if isinstance(step, dict)
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for tool_name in tools:
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        deduped.append(tool_name)
    return deduped


def _validate_tool_policy_shape(tool_policy: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for field_name in ("allowlist", "denylist", "allow_patterns", "deny_patterns"):
        if field_name in tool_policy and not isinstance(tool_policy.get(field_name), list):
            errors.append(
                {
                    "code": "invalid_tool_policy_field",
                    "message": f"tool_policy.{field_name} must be a list of strings",
                }
            )
    if "allow_read_only" in tool_policy and not isinstance(tool_policy.get("allow_read_only"), bool):
        errors.append(
            {
                "code": "invalid_tool_policy_field",
                "message": "tool_policy.allow_read_only must be a boolean",
            }
        )
    return errors


__all__ = ["validate_phase_payload"]
