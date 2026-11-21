"""Setup helpers for the standard agent loop.

Explicit-first: loop setup never classifies the user message with text regexes, because a
workflow is selected explicitly; summary domains come solely from explicit coverage settings
(a scenario profile's ``enforce_domain_coverage`` with its ``required_domains``), never from prompt keywords.
"""

from __future__ import annotations

from typing import Any

from app.services.request_analysis import build_request_analysis

from ....services.instructions.resolve import INSTRUCTIONS_METADATA_KEY
from ....services.workflow_contracts.decisions import (
    apply_workflow_decisions_to_contract,
    recorded_workflow_decisions,
)
from ....services.workflow_contracts.selected_contract import build_selected_workflow_contract
from ....services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY, WORKFLOW_DECISIONS_ANALYSIS_KEY
from ...core.turn.turn_diff import TurnDiffTracker
from ..control._loop_workflow_contract_state import (
    persist_workflow_contract_in_session,
    resolve_workflow_contract_for_turn,
)
from ._loop_workflow_scaffold import build_workflow_step_scaffold


def _turn_project_ids(tool_context: Any) -> tuple[str, str]:
    """The explicit project id of the turn and the project id it works in (explicit first)."""
    explicit_project_id = str((tool_context.project_config or {}).get("project_id") or "").strip()
    project_id = explicit_project_id or next(
        (str(item).strip() for item in (tool_context.project_ids or []) if str(item).strip()),
        "",
    )
    return explicit_project_id, project_id


def _required_summary_domains(context_plan: Any) -> set[str]:
    required_domains: set[str] = set()
    if getattr(context_plan, "enforce_domain_coverage", False):
        required_domains.update(
            {str(domain) for domain in (getattr(context_plan, "required_domains", []) or []) if str(domain).strip()}
        )
    return required_domains


def _turn_request_analysis(
    *, prepared: Any, context_plan: Any, current_turn_content: str, required_domains: set[str]
) -> dict[str, Any]:
    request_analysis = build_request_analysis(
        current_turn_content,
        route_reason=str(getattr(context_plan, "route_reason", "") or ""),
        required_domains=sorted(required_domains),
        context_domains=getattr(context_plan, "domains", []) or [],
        enforce_domain_coverage=bool(getattr(context_plan, "enforce_domain_coverage", False)),
    )
    routing_policy_resolution = prepared.session_metadata.get(ROUTING_RESOLUTION_KEY)
    if isinstance(routing_policy_resolution, dict):
        request_analysis[ROUTING_RESOLUTION_KEY] = routing_policy_resolution
    instructions = prepared.session_metadata.get(INSTRUCTIONS_METADATA_KEY)
    if isinstance(instructions, list):
        request_analysis[INSTRUCTIONS_METADATA_KEY] = instructions
    return request_analysis


def _selected_workflow_contract(
    *,
    prepared: Any,
    context_plan: Any,
    current_turn_content: str,
    request_analysis: dict[str, Any],
    explicit_project_id: str,
    capability_type: str,
) -> dict[str, Any] | None:
    """The contract of the workflow the turn's routing resolution selected, with the session's governance."""
    workflow_input = str(request_analysis.get("canonical_message") or current_turn_content or "").strip()
    # The session's closed workflow decisions ride on the loop's analysis.
    recorded_decisions = recorded_workflow_decisions(prepared.session_metadata)
    if recorded_decisions:
        request_analysis[WORKFLOW_DECISIONS_ANALYSIS_KEY] = dict(recorded_decisions)
    # Only the workflow the turn's routing resolution selected gets a contract (roadmap item 5),
    # built exactly as on the strategy path: builder output plus the definition's governance.
    built_workflow_contract = build_selected_workflow_contract(
        workflow_input,
        request_analysis=request_analysis,
        routing_resolution=prepared.session_metadata.get(ROUTING_RESOLUTION_KEY),
        workflow_decisions=recorded_decisions,
        route_reason=str(getattr(context_plan, "route_reason", "") or ""),
        project_id=explicit_project_id,
        capability_type=capability_type,
    )
    workflow_contract = resolve_workflow_contract_for_turn(
        current_turn_content=current_turn_content,
        built_workflow_contract=built_workflow_contract,
        session_metadata=prepared.session_metadata,
    )
    return _apply_session_governance(workflow_contract, prepared)


def _apply_session_governance(workflow_contract: dict[str, Any] | None, prepared: Any) -> dict[str, Any] | None:
    from ....services.secure_work.coding.verification_contract import (
        apply_verification_contract_to_workflow_contract,
    )

    workflow_contract = apply_verification_contract_to_workflow_contract(
        workflow_contract,
        prepared.session_metadata,
    )
    return apply_workflow_decisions_to_contract(workflow_contract, prepared.session_metadata)


def initialize_standard_loop_state(
    *,
    prepared,
    capability_type: str,
    current_turn_content: str,
    agent_definition: dict | None,
    max_iterations: int | None,
    thinking_level: str | None,
    map_reasoning_effort,
) -> dict[str, Any]:
    context_plan = prepared.context_plan
    explicit_project_id, project_id = _turn_project_ids(prepared.tool_context)
    default_iterations = 64 if capability_type == "change" else 32
    provider_reasoning_effort = map_reasoning_effort(thinking_level)

    required_domains = _required_summary_domains(context_plan)
    request_analysis = _turn_request_analysis(
        prepared=prepared,
        context_plan=context_plan,
        current_turn_content=current_turn_content,
        required_domains=required_domains,
    )
    workflow_contract = _selected_workflow_contract(
        prepared=prepared,
        context_plan=context_plan,
        current_turn_content=current_turn_content,
        request_analysis=request_analysis,
        explicit_project_id=explicit_project_id,
        capability_type=capability_type,
    )
    # The AWS budget plan and the execution-contract trigger come from the selected contract only.
    if workflow_contract:
        request_analysis["workflow_contract"] = workflow_contract
        persist_workflow_contract_in_session(
            current_session=prepared.current_session,
            workflow_contract=workflow_contract,
        )

    workflow_scaffold = build_workflow_step_scaffold(
        workflow_contract=workflow_contract,
        agent_definition=agent_definition,
        capability_type=capability_type,
    )
    if workflow_scaffold["active_steps"]:
        default_iterations = 64
    resolved_max_iterations = int(max_iterations) if max_iterations and int(max_iterations) > 0 else default_iterations
    return _initial_loop_state(
        workflow_scaffold=workflow_scaffold,
        default_iterations=default_iterations,
        explicit_project_id=explicit_project_id,
        max_iterations=resolved_max_iterations,
        project_id=project_id,
        provider_reasoning_effort=provider_reasoning_effort,
        request_analysis=request_analysis,
        required_domains=required_domains,
        workflow_contract=workflow_contract,
    )


def _initial_loop_state(
    *,
    workflow_scaffold: dict[str, Any],
    default_iterations: int,
    explicit_project_id: str,
    max_iterations: int,
    project_id: str,
    provider_reasoning_effort: Any,
    request_analysis: dict[str, Any],
    required_domains: set[str],
    workflow_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "agent_definition": workflow_scaffold["agent_definition"],
        "active_steps": workflow_scaffold["active_steps"],
        "current_step_index": 0,
        "current_step_iterations": 0,
        "current_step_tool_activity": False,
        "current_step_wrapup_forced": False,
        "covered_evidence_axes": set(),
        "covered_summary_domains": set(),
        "default_iterations": default_iterations,
        "duplicate_no_tool_response_count": 0,
        "executed_tool_names": set(),
        "explicit_project_id": explicit_project_id,
        "forced_tool_calls": None,
        "injected_workflow_agent": workflow_scaffold["injected_workflow_agent"],
        "last_no_tool_response_content": "",
        "last_no_tool_response_signature": None,
        "last_no_tool_response_step_index": None,
        "latest_repo_state": {},
        "max_iterations": max_iterations,
        "project_id": project_id,
        "provider_reasoning_effort": provider_reasoning_effort,
        "repeated_previous_step_summary_count": 0,
        "request_analysis": request_analysis,
        "required_domains": required_domains,
        "step_tool_history": [],
        "step_tool_history_index": None,
        "synthetic_workflow_agent": workflow_scaffold["synthetic_workflow_agent"],
        "tdd_cycle_state": None,
        "tdd_cycle_step_index": None,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "turn_diff_tracker": TurnDiffTracker(),
        "turn_tool_history": [],
        "workflow_artifact_ready_for_final_response": False,
        "workflow_contract": workflow_contract,
        "workflow_final_answer_prompted": False,
    }
