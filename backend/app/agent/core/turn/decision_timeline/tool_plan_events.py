"""Timeline events of tool planning: the offered catalog, the plan, its contract and the planner call."""

from __future__ import annotations

from typing import Any

from .timeline import append_decision_timeline_event, compact_items


def append_tool_catalog_event(
    context_snapshot: dict[str, Any],
    *,
    allowed_tool_names: set[str] | list[str],
    tool_definition_count: int,
    session_tool_catalog: dict[str, Any] | None = None,
    session_tool_catalog_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    visible_tools, omitted = compact_items(list(allowed_tool_names or []))
    detail = f"{tool_definition_count} tools are available to the selected runtime."
    if omitted:
        detail += f" {omitted} additional tools were omitted from the trace preview."
    catalog = session_tool_catalog if isinstance(session_tool_catalog, dict) else {}
    resolution = (
        session_tool_catalog_resolution
        if isinstance(session_tool_catalog_resolution, dict)
        else {}
    )
    decision_summary = (
        resolution.get("decision_summary")
        if isinstance(resolution.get("decision_summary"), dict)
        else {}
    )
    return append_decision_timeline_event(
        context_snapshot,
        phase="catalog",
        title="Tool catalog resolved",
        status="ok" if tool_definition_count else "info",
        detail=detail,
        metadata={
            "tool_count": tool_definition_count,
            "tools": visible_tools,
            "omitted_tool_count": omitted,
            "catalog_mode": catalog.get("mode"),
            "catalog_contract_kind": catalog.get("contract_kind"),
            "catalog_contract_version": catalog.get("contract_version"),
            "resolver_contract_kind": resolution.get("contract_kind"),
            "resolver_status": resolution.get("status"),
            "resolver_runtime_effect": resolution.get("runtime_effect"),
            "resolver_scope_source": decision_summary.get("scope_source"),
            "resolver_policy_effect_counts": decision_summary.get("policy_effect_counts"),
            "policy_source": catalog.get("policy_source"),
            "routing_policy_id": catalog.get("routing_policy_id"),
            "routing_policy_version_id": catalog.get("routing_policy_version_id"),
            "routing_policy_matched_group_id": catalog.get("routing_policy_matched_group_id"),
            "policy_allowlist_count": catalog.get("policy_allowlist_count"),
            "policy_denylist_count": catalog.get("policy_denylist_count"),
            "denied_tools": catalog.get("denied_tools"),
            "skipped_policy_tools": catalog.get("skipped_policy_tools"),
            "unavailable_policy_tools": catalog.get("unavailable_policy_tools"),
            "category_counts": catalog.get("category_counts"),
            "risk_counts": catalog.get("risk_counts"),
            "approval_hint_count": catalog.get("approval_hint_count"),
            "session_scope": catalog.get("session_scope"),
        },
    )


def append_forced_tool_plan_event(
    context_snapshot: dict[str, Any],
    *,
    forced_tool_calls: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    planned_tools = [
        str(call.get("function", {}).get("name") or call.get("tool_name") or "").strip()
        for call in forced_tool_calls or []
        if isinstance(call, dict)
    ]
    if planned_tools:
        return append_decision_timeline_event(
            context_snapshot,
            phase="plan",
            title="Code planner prepared tool calls",
            status="ok",
            detail="Current routing prepared deterministic tool calls before model dispatch.",
            metadata={"planned_tools": [tool for tool in planned_tools if tool]},
        )
    return append_decision_timeline_event(
        context_snapshot,
        phase="plan",
        title="Model may choose from catalog",
        status="info",
        detail="No deterministic forced tool call was prepared for this dispatch.",
    )


def append_tool_plan_contract_event(
    context_snapshot: dict[str, Any],
    *,
    tool_plan_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = tool_plan_contract if isinstance(tool_plan_contract, dict) else {}
    validation = contract.get("validation") if isinstance(contract.get("validation"), dict) else {}
    intent_contract = contract.get("intent_contract") if isinstance(contract.get("intent_contract"), dict) else {}
    selected_tools = [
        str(item.get("tool") or "").strip()
        for item in contract.get("selected_tools") or []
        if isinstance(item, dict) and str(item.get("tool") or "").strip()
    ]
    is_valid = bool(validation.get("valid"))
    status = "ok" if is_valid else "warning"
    detail = "Trace-only plan contract drafted and validated."
    if contract.get("mode") == "trace_only":
        detail += " Runtime behavior is unchanged."
    return append_decision_timeline_event(
        context_snapshot,
        phase="plan_contract",
        title="LLM tool plan contract drafted",
        status=status,
        detail=detail,
        metadata={
            "mode": contract.get("mode"),
            "source": contract.get("source"),
            "intent_class": contract.get("intent_class"),
            "confidence": contract.get("confidence"),
            "intent_contract_version": intent_contract.get("version"),
            "intent_source": intent_contract.get("source"),
            "intent_fallback_policy": intent_contract.get("fallback_policy"),
            "intent_requested_domains": intent_contract.get("requested_domains"),
            "intent_catalog_policy_source": intent_contract.get("catalog_policy_source"),
            "intent_denied_tool_count": intent_contract.get("denied_tool_count"),
            "selected_tools": selected_tools,
            "max_tool_calls": contract.get("max_tool_calls"),
            "requires_clarification": contract.get("requires_clarification"),
            "validation_valid": validation.get("valid"),
            "validation_errors": validation.get("errors"),
            "validation_warnings": validation.get("warnings"),
        },
    )


def append_tool_execution_control_event(
    context_snapshot: dict[str, Any],
    *,
    execution_control_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = execution_control_contract if isinstance(execution_control_contract, dict) else {}
    budget = contract.get("budget") if isinstance(contract.get("budget"), dict) else {}
    policy_effects = contract.get("policy_effects") if isinstance(contract.get("policy_effects"), dict) else {}
    counts = policy_effects.get("counts") if isinstance(policy_effects.get("counts"), dict) else {}
    status_value = str(contract.get("status") or "unknown").strip()
    if status_value == "ready":
        status = "ok"
    elif status_value in {"blocked", "clarification_required"}:
        status = "warning"
    else:
        status = "info"
    return append_decision_timeline_event(
        context_snapshot,
        phase="execution_control",
        title="Tool execution control drafted",
        status=status,
        detail="Trace-only execution-control contract prepared. Runtime behavior is unchanged.",
        metadata={
            "mode": contract.get("mode"),
            "contract_kind": contract.get("contract_kind"),
            "contract_status": status_value,
            "runtime_effect": contract.get("runtime_effect"),
            "intent_class": contract.get("intent_class"),
            "selected_tools": contract.get("selected_tools"),
            "max_tool_calls": budget.get("max_tool_calls"),
            "planned_tool_count": budget.get("planned_tool_count"),
            "remaining_after_plan": budget.get("remaining_after_plan"),
            "budget_exceeded": budget.get("budget_exceeded"),
            "stop_criteria": contract.get("stop_criteria"),
            "validation_valid": (contract.get("validation") or {}).get("valid")
            if isinstance(contract.get("validation"), dict)
            else None,
            "policy_effect_counts": counts,
            "blockers": contract.get("blockers"),
        },
    )


def append_tool_plan_prompt_event(
    context_snapshot: dict[str, Any],
    *,
    prompt_packet: dict[str, Any] | None,
) -> dict[str, Any]:
    packet = prompt_packet if isinstance(prompt_packet, dict) else {}
    allowed_catalog = packet.get("allowed_tool_catalog") if isinstance(packet.get("allowed_tool_catalog"), list) else []
    return append_decision_timeline_event(
        context_snapshot,
        phase="planner_io",
        title="LLM planner prompt prepared",
        status="info",
        detail="Trace-only planner input was prepared. No separate planner call was executed in this slice.",
        metadata={
            "mode": packet.get("mode"),
            "source": packet.get("source"),
            "planner_call_status": packet.get("planner_call_status"),
            "intent_hint": packet.get("intent_hint"),
            "catalog_entry_count": len(allowed_catalog),
            "omitted_tool_count": packet.get("omitted_tool_count"),
        },
    )


def append_tool_planner_call_event(
    context_snapshot: dict[str, Any],
    *,
    planner_result: dict[str, Any] | None,
) -> dict[str, Any]:
    result = planner_result if isinstance(planner_result, dict) else {}
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
    call_status = str(result.get("call_status") or "unknown").strip()
    if call_status == "completed" and validation.get("valid"):
        status = "ok"
    elif call_status in {"failed", "completed"}:
        status = "warning"
    else:
        status = "info"
    return append_decision_timeline_event(
        context_snapshot,
        phase="planner_call",
        title="LLM planner call evaluated",
        status=status,
        detail="Model-authored planner output was recorded for trace-only inspection.",
        metadata={
            "call_status": call_status,
            "skip_reason": result.get("skip_reason"),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "intent_class": plan.get("intent_class"),
            "selected_tool_count": len(plan.get("selected_tools") or []) if isinstance(plan, dict) else 0,
            "validation_valid": validation.get("valid"),
            "validation_errors": validation.get("errors"),
            "validation_warnings": validation.get("warnings"),
            "attempt_count": len(result.get("runtime_attempts") or []),
        },
    )
