"""Trace-only LLM tool plan contract drafting and validation."""

from __future__ import annotations

from typing import Any

from ..workflow_contracts.registry import workflow_phase_tool_names
from ..workflow_runs.phase_marker import is_run_phase_contract
from .phase_plan import PHASE_FALLBACK_POLICY, PHASE_INTENT, phase_tool_plan

CONTRACT_VERSION = 1
PLAN_MODE = "trace_only"
PLAN_SOURCE = "contract_draft"
INTENT_CONTRACT_VERSION = 1

SUPPORTED_INTENTS = {
    "workflow_process",
    PHASE_INTENT,
    "unknown",
}


def _catalog_entries_by_name(session_tool_catalog: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    catalog = session_tool_catalog if isinstance(session_tool_catalog, dict) else {}
    entries = catalog.get("entries") if isinstance(catalog.get("entries"), list) else []
    return {
        str(entry.get("name") or "").strip(): entry
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("name") or "").strip()
    }


def _requested_domains(request_analysis: dict[str, Any] | None) -> set[str]:
    analysis = request_analysis if isinstance(request_analysis, dict) else {}
    domains = analysis.get("requested_domains")
    if not isinstance(domains, list):
        domains = analysis.get("domains")
    if not isinstance(domains, list):
        return set()
    return {str(domain or "").strip().lower() for domain in domains if str(domain or "").strip()}


def _requested_domain_list(request_analysis: dict[str, Any] | None) -> list[str]:
    return sorted(_requested_domains(request_analysis))


def _infer_intent_class(*, workflow_contract: dict[str, Any] | None) -> str:
    """Intent class comes ONLY from the explicit workflow contract branch.

    A turn without a contract-declared intent is explicitly ``unknown``
    (standard path / clarification), never keyword-guessed from the prompt.
    A phase turn of a workflow run is planned from the phase's own surface.
    """
    if is_run_phase_contract(workflow_contract):
        return PHASE_INTENT
    if workflow_phase_tool_names(workflow_contract):
        return "workflow_process"
    return "unknown"


def _selected_tool(tool: str, *, reason: str, expected_evidence: list[str]) -> dict[str, Any]:
    return {
        "tool": tool,
        "reason": reason,
        "expected_evidence": expected_evidence,
    }


def _select_workflow_process_tools(
    workflow_contract: dict[str, Any] | None,
    *,
    catalog_entries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for name in workflow_phase_tool_names(workflow_contract):
        if name not in catalog_entries:
            continue
        selected.append(
            _selected_tool(
                name,
                reason="Execute the visible workflow process step with an authorized tool.",
                expected_evidence=["workflow_step_evidence", "auditable_tool_trace"],
            )
        )
    return selected


def _draft_tools_for_intent(
    intent_class: str,
    catalog_entries: dict[str, dict[str, Any]],
    *,
    workflow_contract: dict[str, Any] | None = None,
    workflow_process_completed: bool = False,
) -> tuple[list[dict], list[str], int]:
    if intent_class == PHASE_INTENT:
        return phase_tool_plan(catalog_entries)
    if intent_class == "workflow_process":
        if workflow_process_completed:
            return (
                [],
                [
                    "workflow_process_completed",
                    "final_answer_from_workflow_evidence",
                    "no_additional_tools_required",
                ],
                0,
            )
        workflow_tools = _select_workflow_process_tools(
            workflow_contract,
            catalog_entries=catalog_entries,
        )
        workflow_tool_budget = max(len(workflow_phase_tool_names(workflow_contract)), len(workflow_tools), 1)
        return (
            workflow_tools,
            ["workflow_process_steps_completed", "answer_grounded_in_workflow_evidence"],
            workflow_tool_budget,
        )
    return ([], ["request_requires_clarification_or_direct_answer"], 0)


def _confidence_for_intent(intent_class: str, selected_tools: list[dict[str, Any]]) -> float:
    if intent_class == "unknown":
        return 0.2
    return 0.85 if selected_tools else 0.45


def _build_intent_contract(
    *,
    intent_class: str,
    confidence: float,
    current_turn_content: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    session_tool_catalog: dict[str, Any] | None,
    selected_tools: list[dict[str, Any]],
    workflow_process_completed: bool = False,
) -> dict[str, Any]:
    catalog = session_tool_catalog if isinstance(session_tool_catalog, dict) else {}
    workflow = workflow_contract if isinstance(workflow_contract, dict) else {}
    selected_tool_names = [
        str(item.get("tool") or "").strip()
        for item in selected_tools
        if isinstance(item, dict) and str(item.get("tool") or "").strip()
    ]
    denied_tools = [
        str(item).strip()
        for item in catalog.get("denied_tools") or []
        if str(item).strip()
    ]
    skipped_policy_tools = [
        str(item).strip()
        for item in catalog.get("skipped_policy_tools") or []
        if str(item).strip()
    ]
    unavailable_policy_tools = [
        str(item).strip()
        for item in catalog.get("unavailable_policy_tools") or []
        if str(item).strip()
    ]
    fallback_policy = "clarify_or_answer_without_tools" if intent_class == "unknown" else "use_allowed_catalog_only"
    if intent_class == PHASE_INTENT:
        fallback_policy = PHASE_FALLBACK_POLICY
    elif intent_class == "workflow_process" and not selected_tool_names and workflow_process_completed:
        fallback_policy = "final_answer_from_completed_workflow"
    elif intent_class == "workflow_process" and selected_tool_names:
        fallback_policy = "workflow_process_toolset"
    elif intent_class == "workflow_process":
        fallback_policy = "workflow_process_tools_unavailable"
    if unavailable_policy_tools and not selected_tool_names and not workflow_process_completed:
        fallback_policy = "policy_matched_but_required_tools_unavailable"
    return {
        "version": INTENT_CONTRACT_VERSION,
        "source": "deterministic_trace_contract",
        "intent_class": intent_class,
        "confidence": confidence,
        "requested_domains": _requested_domain_list(request_analysis),
        "workflow_contract_allowed_tools": [
            str(name).strip()
            for name in (workflow.get("allowed_tools") or [])
            if str(name or "").strip()
        ],
        "workflow_id": workflow.get("workflow_id"),
        "workflow_class": workflow.get("workflow_class"),
        "catalog_contract_version": catalog.get("contract_version"),
        "catalog_policy_source": catalog.get("policy_source"),
        "catalog_tool_count": catalog.get("tool_count"),
        "selected_tool_count": len(selected_tool_names),
        "denied_tool_count": len(denied_tools),
        "skipped_policy_tool_count": len(skipped_policy_tools),
        "unavailable_policy_tool_count": len(unavailable_policy_tools),
        "fallback_policy": fallback_policy,
        "requires_clarification": intent_class == "unknown",
        "workflow_process_required": intent_class == "workflow_process",
        "workflow_process_completed": intent_class == "workflow_process" and workflow_process_completed,
        "user_request_chars": len(str(current_turn_content or "")),
    }


def _contract_allowed_tool_names(plan: dict[str, Any]) -> set[str]:
    intent_contract = plan.get("intent_contract") if isinstance(plan.get("intent_contract"), dict) else {}
    names = intent_contract.get("workflow_contract_allowed_tools")
    return {str(name).strip() for name in (names or []) if str(name or "").strip()}


def validate_tool_plan_contract(
    plan: dict[str, Any],
    *,
    session_tool_catalog: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate the contract without authorizing or executing it."""

    errors: list[str] = []
    warnings: list[str] = []
    catalog_entries = _catalog_entries_by_name(session_tool_catalog)
    intent_class = str(plan.get("intent_class") or "").strip()
    selected_tools = plan.get("selected_tools") if isinstance(plan.get("selected_tools"), list) else []
    stop_criteria = plan.get("stop_criteria") if isinstance(plan.get("stop_criteria"), list) else []

    if plan.get("version") != CONTRACT_VERSION:
        errors.append("unsupported_contract_version")
    if plan.get("mode") != PLAN_MODE:
        errors.append("unsupported_contract_mode")
    if intent_class not in SUPPORTED_INTENTS:
        errors.append("unsupported_intent_class")

    try:
        confidence = float(plan.get("confidence"))
    except (TypeError, ValueError):
        confidence = -1.0
    if confidence < 0.0 or confidence > 1.0:
        errors.append("confidence_out_of_bounds")

    try:
        max_tool_calls = int(plan.get("max_tool_calls"))
    except (TypeError, ValueError):
        max_tool_calls = -1
    if max_tool_calls < 0:
        errors.append("max_tool_calls_out_of_bounds")
    phase_turn = intent_class == PHASE_INTENT
    if len(selected_tools) > max_tool_calls and not phase_turn:
        # A phase plan declares no budget (0): the loop's limit and the phase checks bound the turn.
        errors.append("selected_tools_exceed_budget")
    if not stop_criteria:
        errors.append("missing_stop_criteria")

    for item in selected_tools:
        tool_name = str(item.get("tool") or "").strip() if isinstance(item, dict) else ""
        if not tool_name:
            errors.append("selected_tool_missing_name")
            continue
        catalog_entry = catalog_entries.get(tool_name)
        if catalog_entry is None:
            if tool_name in _contract_allowed_tool_names(plan):
                # Adopted-definition toolset: plannable although the
                # turn-start catalog was narrowed before the selection;
                # dispatch-time governance still checks the call.
                warnings.append(f"selected_tool_from_workflow_contract:{tool_name}")
                continue
            errors.append(f"selected_tool_not_in_catalog:{tool_name}")
            continue
        if catalog_entry.get("approval_hint"):
            # A phase's surface keeps its approval tools: the dispatch approval gate decides each call.
            (warnings if phase_turn else errors).append(f"selected_tool_requires_approval:{tool_name}")
        if catalog_entry.get("risk_level") == "high":
            warnings.append(f"selected_tool_high_risk:{tool_name}")

    if intent_class == "unknown" and selected_tools:
        warnings.append("unknown_intent_has_selected_tools")
    intent_contract = plan.get("intent_contract") if isinstance(plan.get("intent_contract"), dict) else {}
    workflow_process_completed = bool(intent_contract.get("workflow_process_completed"))
    if intent_class == "workflow_process" and not selected_tools and not workflow_process_completed:
        errors.append("workflow_process_tools_unavailable")
    elif intent_class != "unknown" and not selected_tools and not workflow_process_completed:
        warnings.append("known_intent_has_no_available_tools")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def build_trace_only_tool_plan_contract(
    *,
    current_turn_content: str,
    request_analysis: dict[str, Any] | None,
    workflow_contract: dict[str, Any] | None,
    session_tool_catalog: dict[str, Any] | None,
    workflow_process_completed: bool = False,
) -> dict[str, Any]:
    """Draft and validate a visible plan contract without changing runtime behavior."""

    catalog_entries = _catalog_entries_by_name(session_tool_catalog)
    intent_class = _infer_intent_class(workflow_contract=workflow_contract)
    selected_tools, stop_criteria, max_tool_calls = _draft_tools_for_intent(
        intent_class,
        catalog_entries,
        workflow_contract=workflow_contract,
        workflow_process_completed=workflow_process_completed,
    )
    confidence = _confidence_for_intent(intent_class, selected_tools)
    plan = {
        "version": CONTRACT_VERSION,
        "mode": PLAN_MODE,
        "source": PLAN_SOURCE,
        "intent_class": intent_class,
        "confidence": confidence,
        "selected_tools": selected_tools,
        "stop_criteria": stop_criteria,
        "max_tool_calls": max_tool_calls,
        "requires_clarification": intent_class == "unknown",
        "intent_contract": _build_intent_contract(
            intent_class=intent_class,
            confidence=confidence,
            current_turn_content=current_turn_content,
            request_analysis=request_analysis,
            workflow_contract=workflow_contract,
            session_tool_catalog=session_tool_catalog,
            selected_tools=selected_tools,
            workflow_process_completed=workflow_process_completed,
        ),
    }
    plan["validation"] = validate_tool_plan_contract(plan, session_tool_catalog=session_tool_catalog)
    return plan


__all__ = ["build_trace_only_tool_plan_contract", "validate_tool_plan_contract"]
