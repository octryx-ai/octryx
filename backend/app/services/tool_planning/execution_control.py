"""Execution-control contracts for tool plans."""

from __future__ import annotations

from typing import Any

from .phase_plan import PHASE_INTENT, phase_execution_control

MAX_VISIBLE_TOOLS = 40
CONTROL_CONTRACT_VERSION = 1


def _selected_tool_names(plan_contract: dict[str, Any]) -> list[str]:
    selected = plan_contract.get("selected_tools") if isinstance(plan_contract.get("selected_tools"), list) else []
    names: list[str] = []
    seen: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or "").strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names[:MAX_VISIBLE_TOOLS]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validation_summary(plan_contract: dict[str, Any]) -> dict[str, Any]:
    validation = plan_contract.get("validation") if isinstance(plan_contract.get("validation"), dict) else {}
    return {
        "valid": bool(validation.get("valid")),
        "errors": _string_list(validation.get("errors")),
        "warnings": _string_list(validation.get("warnings")),
    }


def _policy_effects(catalog_resolution: dict[str, Any]) -> dict[str, Any]:
    summary = (
        catalog_resolution.get("decision_summary")
        if isinstance(catalog_resolution.get("decision_summary"), dict)
        else {}
    )
    counts = summary.get("policy_effect_counts") if isinstance(summary.get("policy_effect_counts"), dict) else {}
    catalog = catalog_resolution.get("catalog") if isinstance(catalog_resolution.get("catalog"), dict) else {}
    return {
        "counts": {
            "denied": int(counts.get("denied") or 0),
            "skipped": int(counts.get("skipped") or 0),
            "unavailable": int(counts.get("unavailable") or 0),
        },
        "denied_tools": _string_list(catalog.get("denied_tools"))[:MAX_VISIBLE_TOOLS],
        "skipped_policy_tools": _string_list(catalog.get("skipped_policy_tools"))[:MAX_VISIBLE_TOOLS],
        "unavailable_policy_tools": _string_list(catalog.get("unavailable_policy_tools"))[:MAX_VISIBLE_TOOLS],
    }


def _budget_summary(plan_contract: dict[str, Any], selected_tools: list[str]) -> dict[str, Any]:
    try:
        max_tool_calls = max(int(plan_contract.get("max_tool_calls") or 0), 0)
    except (TypeError, ValueError):
        max_tool_calls = 0
    remaining = max(max_tool_calls - len(selected_tools), 0)
    return {
        "max_tool_calls": max_tool_calls,
        "planned_tool_count": len(selected_tools),
        "remaining_after_plan": remaining,
        "budget_exceeded": len(selected_tools) > max_tool_calls,
    }


def build_tool_execution_control_contract(
    *,
    session_tool_catalog_resolution: dict[str, Any] | None,
    tool_plan_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build an execution-control contract for the drafted tool plan."""

    catalog_resolution = (
        session_tool_catalog_resolution
        if isinstance(session_tool_catalog_resolution, dict)
        else {}
    )
    plan_contract = tool_plan_contract if isinstance(tool_plan_contract, dict) else {}
    selected_tools = _selected_tool_names(plan_contract)
    validation = _validation_summary(plan_contract)
    policy_effects = _policy_effects(catalog_resolution)
    budget = _budget_summary(plan_contract, selected_tools)
    requires_clarification = bool(plan_contract.get("requires_clarification"))
    stop_criteria = _string_list(plan_contract.get("stop_criteria"))
    blockers: list[str] = []
    if requires_clarification:
        blockers.append("clarification_required")
    if not validation["valid"]:
        blockers.append("plan_validation_failed")
    if budget["budget_exceeded"]:
        blockers.append("planned_tools_exceed_budget")
    if policy_effects["counts"]["unavailable"] and not selected_tools:
        blockers.append("policy_required_tools_unavailable")
    if not selected_tools and not requires_clarification:
        blockers.append("no_selected_tools")

    if blockers:
        status = "clarification_required" if "clarification_required" in blockers else "blocked"
    elif not selected_tools:
        status = "no_tool_plan"
    else:
        status = "ready"
    enforcement_enabled = status == "ready"

    enforcement = {
        "enabled": enforcement_enabled,
        "selected_tool_gate": enforcement_enabled,
        "budget_gate": enforcement_enabled,
        "max_tool_calls": budget["max_tool_calls"],
    }

    contract = {
        "version": CONTROL_CONTRACT_VERSION,
        "mode": "runtime_enforced",
        "contract_kind": "tool_execution_control",
        "status": status,
        "runtime_effect": "selected_tool_and_budget_gate" if enforcement_enabled else "inactive_until_ready",
        "intent_class": plan_contract.get("intent_class") or "unknown",
        "selected_tools": selected_tools,
        "budget": budget,
        "stop_criteria": stop_criteria,
        "validation": validation,
        "policy_effects": policy_effects,
        "blockers": blockers,
        "enforcement": enforcement,
        "next_actions": [
            "runtime_enforces_ready_contracts",
            "future_slice_may_drive_planner_execution",
        ],
    }
    if contract["intent_class"] == PHASE_INTENT:
        # A phase turn's gate is the phase's whole surface: never a narrowing, never a call budget.
        return phase_execution_control(contract, plan_contract)
    return contract


__all__ = ["build_tool_execution_control_contract"]
