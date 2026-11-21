"""Routing and runtime selection for a standard loop turn."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.workflow_contracts.registry import workflow_contract_from_request_analysis

from ....services.coordinator_mode_routing_policy import (
    CoordinatorRoutingSignals,
    decide_coordinator_mode,
)
from ....services.model_selection_policy import (
    coding_discipline_for_role,
    reasoning_stage_for_turn,
    reasoning_task_type_for_turn,
)


def _coordinator_signal_value(*sources: Any, key: str) -> Any:
    for source in sources:
        if not isinstance(source, dict):
            continue
        coordinator_payload = source.get("coordinator")
        if isinstance(coordinator_payload, dict) and key in coordinator_payload:
            return coordinator_payload.get(key)
        if key in source:
            return source.get(key)
    return None


def _optional_text(value: Any) -> str | None:
    return str(value or "").strip() or None


def _coordinator_routing_signals(
    *,
    workflow_contract: dict[str, Any] | None,
    request_analysis: dict[str, Any] | None,
    context_plan: Any,
    current_step: dict[str, Any] | None,
    current_step_for_runtime: dict[str, Any] | None,
) -> CoordinatorRoutingSignals:
    context_plan_dict = context_plan if isinstance(context_plan, dict) else {}
    workflow_id = str((workflow_contract or {}).get("workflow_id") or "").strip()

    def signal(key: str) -> Any:
        return _coordinator_signal_value(
            current_step_for_runtime, current_step, request_analysis, context_plan_dict, key=key
        )

    expected_child_count = signal("expected_child_count")
    try:
        normalized_child_count = max(int(expected_child_count or 0), 0)
    except (TypeError, ValueError):
        normalized_child_count = 0

    return CoordinatorRoutingSignals(
        deterministic_workflow_id=workflow_id or None,
        target_worker_id=_optional_text(signal("target_worker_id")),
        required_worker_domain=_optional_text(signal("required_worker_domain")),
        requested_action=_optional_text(signal("requested_action")),
        requires_worker_assignment=bool(signal("requires_worker_assignment")),
        requires_parallel_children=bool(signal("requires_parallel_children")),
        expected_child_count=normalized_child_count,
        requires_parent_resume=bool(signal("requires_parent_resume")),
    )


def _normalize_coordinator_routing(
    *,
    workflow_contract: dict[str, Any] | None,
    request_analysis: dict[str, Any] | None,
    context_plan: Any,
    current_step: dict[str, Any] | None,
    current_step_for_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    signals = _coordinator_routing_signals(
        workflow_contract=workflow_contract,
        request_analysis=request_analysis,
        context_plan=context_plan,
        current_step=current_step,
        current_step_for_runtime=current_step_for_runtime,
    )
    decision = decide_coordinator_mode(signals)
    return {
        "conflicts": list(decision.conflicts),
        "explicit": decision.mode != "manual_review",
        "mode": decision.mode,
        "rationale": decision.rationale,
        "requires_manual_review": decision.requires_manual_review,
        "signals": {
            "deterministic_workflow_id": signals.deterministic_workflow_id or "",
            "expected_child_count": signals.expected_child_count,
            "requested_action": signals.requested_action or "",
            "required_worker_domain": signals.required_worker_domain or "",
            "requires_parallel_children": signals.requires_parallel_children,
            "requires_parent_resume": signals.requires_parent_resume,
            "requires_worker_assignment": signals.requires_worker_assignment,
            "target_worker_id": signals.target_worker_id or "",
        },
    }


def prepare_runtime_routing(
    *,
    runtimes: list[dict[str, Any]],
    capability_type: str,
    context_plan,
    request_analysis: dict[str, Any],
    current_step,
    current_step_for_runtime,
    step_tool_history: list[dict[str, Any]],
    _model_role_for_current_subtask: Callable[..., str],
) -> dict[str, Any]:
    """The iteration's routing facts; the runtimes are the turn's, unchanged.

    Every iteration of a turn runs on the runtime chain the turn was prepared with. The
    subtask role, reasoning stage and coding discipline are recorded as observations only:
    they never reorder or replace the runtimes. A runtime changes within a turn only
    through the provider fallback's explicit, logged failover.
    """
    current_subtask_role = _model_role_for_current_subtask(
        current_step=current_step,
        current_step_for_runtime=current_step_for_runtime,
        step_tool_history=step_tool_history,
    )
    current_reasoning_task_type = reasoning_task_type_for_turn(
        capability_type=capability_type,
        current_step=current_step,
        current_step_for_runtime=current_step_for_runtime,
        context_plan=context_plan,
    )
    current_reasoning_stage = reasoning_stage_for_turn(
        capability_type=capability_type,
        current_step=current_step,
        current_subtask_role=current_subtask_role,
    )
    current_coding_discipline = coding_discipline_for_role(
        capability_type=capability_type,
        current_step=current_step,
        current_subtask_role=current_subtask_role,
    )
    workflow_contract = workflow_contract_from_request_analysis(request_analysis)
    coordinator_routing = _normalize_coordinator_routing(
        workflow_contract=workflow_contract,
        request_analysis=request_analysis,
        context_plan=context_plan,
        current_step=current_step,
        current_step_for_runtime=current_step_for_runtime,
    )
    return {
        "current_coding_discipline": current_coding_discipline,
        "current_reasoning_stage": current_reasoning_stage,
        "current_reasoning_task_type": current_reasoning_task_type,
        "current_runtimes": list(runtimes),
        "current_subtask_role": current_subtask_role,
        "coordinator_routing": coordinator_routing,
        "workflow_contract": workflow_contract,
    }
