"""Runtime enforcement helpers for tool execution-control contracts."""

from __future__ import annotations

from typing import Any

from ..system_config.constants import DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS
from .phase_plan import PHASE_INTENT, phase_call_refusal

META_TOOL_OVERRIDES = {"release_context", "load_tool_artifact"}


def _contract_from_snapshot(context_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    contract = snapshot.get("tool_execution_control_contract")
    return contract if isinstance(contract, dict) else {}


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _max_tool_calls(contract: dict[str, Any]) -> int:
    enforcement = contract.get("enforcement") if isinstance(contract.get("enforcement"), dict) else {}
    budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    raw_value = enforcement.get("max_tool_calls", budget.get("max_tool_calls", 0))
    try:
        return max(int(raw_value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _used_tool_calls(turn_tool_history: list[dict[str, Any]] | None) -> int:
    count = 0
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip()
        result = item.get("result")
        if isinstance(result, dict) and result.get("error"):
            continue
        if tool_name and tool_name not in META_TOOL_OVERRIDES:
            count += 1
    return count


def _required_domains(context_snapshot: dict[str, Any] | None) -> set[str]:
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    domains: set[str] = set()
    for key in ("context_plan", "request_analysis"):
        value = snapshot.get(key)
        if not isinstance(value, dict):
            continue
        raw_domains = value.get("required_domains")
        if isinstance(raw_domains, list):
            domains.update(str(domain).strip().lower() for domain in raw_domains if str(domain).strip())
    return domains


def _is_required_summary_domain_tool(tool_name: str, context_snapshot: dict[str, Any] | None) -> bool:
    required_domains = _required_domains(context_snapshot)
    if not tool_name or not required_domains:
        return False
    return any(tool_name in DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS.get(domain, set()) for domain in required_domains)


def enforce_tool_execution_control(
    *,
    tool_name: str,
    context_snapshot: dict[str, Any] | None,
    turn_tool_history: list[dict[str, Any]] | None,
    current_allowed_tool_names: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return an error result when a ready execution-control contract denies a tool call."""

    if tool_name in META_TOOL_OVERRIDES:
        return None
    contract = _contract_from_snapshot(context_snapshot)
    enforcement = contract.get("enforcement") if isinstance(contract.get("enforcement"), dict) else {}
    if not bool(enforcement.get("enabled")):
        return None
    if contract.get("intent_class") == PHASE_INTENT:
        return phase_call_refusal(tool_name, contract)
    if bool(enforcement.get("deny_all_tools")):
        return {
            "error": (
                "No published workflow process or authorized autonomous source toolset is visible for this "
                "governed source-evidence request."
            ),
            "code": "authorized_workflow_or_toolset_required",
            "reason": "workflow_or_toolset_missing",
            "allowed_tools": [],
            "contract_kind": contract.get("contract_kind"),
            "intent_class": contract.get("intent_class"),
        }

    selected_tools = _string_set(contract.get("selected_tools"))
    step_allowed_tools = {
        str(item or "").strip() for item in (current_allowed_tool_names or set()) if str(item).strip()
    }
    allowed_by_step_contract = bool(tool_name and tool_name in step_allowed_tools)
    if (
        selected_tools
        and tool_name not in selected_tools
        and not allowed_by_step_contract
        and not _is_required_summary_domain_tool(tool_name, context_snapshot)
    ):
        return {
            "error": (
                f"Tool '{tool_name}' is not part of the selected execution plan. "
                f"Planned tools: {', '.join(sorted(selected_tools))}"
            ),
            "code": "tool_execution_control_denied",
            "reason": "tool_not_in_execution_plan",
            "allowed_tools": sorted(selected_tools),
            "contract_kind": contract.get("contract_kind"),
            "intent_class": contract.get("intent_class"),
        }

    max_tool_calls = _max_tool_calls(contract)
    used_tool_calls = _used_tool_calls(turn_tool_history)
    if max_tool_calls and used_tool_calls >= max_tool_calls and not allowed_by_step_contract:
        return {
            "error": (
                f"Tool execution budget exhausted after {used_tool_calls} tool calls. "
                f"Max allowed by the execution-control contract: {max_tool_calls}."
            ),
            "code": "tool_execution_control_budget_exhausted",
            "reason": "max_tool_calls_reached",
            "used_tool_calls": used_tool_calls,
            "max_tool_calls": max_tool_calls,
            "contract_kind": contract.get("contract_kind"),
            "intent_class": contract.get("intent_class"),
        }
    return None


def filter_tool_definitions_for_execution_control(
    *,
    tool_definitions: list[dict[str, Any]],
    execution_control_contract: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter visible tool definitions when a ready execution-control contract is active."""

    contract = execution_control_contract if isinstance(execution_control_contract, dict) else {}
    enforcement = contract.get("enforcement") if isinstance(contract.get("enforcement"), dict) else {}
    selected_tools = _string_set(contract.get("selected_tools"))
    if bool(enforcement.get("deny_all_tools")):
        return [], {
            "applied": True,
            "reason": "authorized_workflow_or_toolset_required",
            "visible_tool_count": 0,
            "selected_tool_count": 0,
            "selected_tools": [],
        }
    if not bool(enforcement.get("enabled")) or not selected_tools:
        return tool_definitions, {
            "applied": False,
            "reason": "contract_not_ready",
            "visible_tool_count": len(tool_definitions),
            "selected_tool_count": len(selected_tools),
        }
    filtered = [
        definition
        for definition in tool_definitions
        if str((definition.get("function") or {}).get("name") or "").strip() in selected_tools
    ]
    return filtered, {
        "applied": True,
        "reason": "ready_execution_control_contract",
        "visible_tool_count": len(filtered),
        "selected_tool_count": len(selected_tools),
        "selected_tools": sorted(selected_tools),
    }


__all__ = ["enforce_tool_execution_control", "filter_tool_definitions_for_execution_control"]
