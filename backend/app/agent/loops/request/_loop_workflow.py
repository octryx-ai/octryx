"""Workflow and forced-tool-call orchestration helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....services.workflow_contracts.registry import workflow_phase_tool_names
from ...core.runtime.trace_runtime import compact_trace_value


def _workflow_process_tool_names(workflow_contract: dict[str, Any] | None) -> set[str]:
    return set(workflow_phase_tool_names(workflow_contract))


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    return str((tool_call.get("function") or {}).get("name") or tool_call.get("tool_name") or "").strip()


def _workflow_planner_mode(workflow_contract: dict[str, Any] | None) -> str:
    if not isinstance(workflow_contract, dict):
        return ""
    return str(workflow_contract.get("planner_mode") or "").strip().lower()


def plan_forced_tool_calls_for_turn(
    *,
    request_analysis: dict[str, Any],
    capability_type: str,
    current_turn_content: str,
    workspace_root: str,
    current_allowed_tool_names: set[str],
    turn_tool_history: list[dict[str, Any]],
    covered_evidence_axes: set[str],
    workflow_contract_from_request_analysis: Callable[[dict[str, Any]], dict[str, Any] | None],
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]],
    _plan_coding_preflight_tool_calls: Callable[..., list[dict[str, Any]] | None],
    allow_coding_preflight: bool = True,
) -> list[dict[str, Any]] | None:
    workflow_contract = workflow_contract_from_request_analysis(request_analysis)
    if _workflow_planner_mode(workflow_contract) == "advisory":
        return None
    if not allow_coding_preflight:
        return None

    coding_preflight_tool_calls = _plan_coding_preflight_tool_calls(
        capability_type=capability_type,
        user_message=current_turn_content,
        workspace_root=workspace_root,
        allowed_tool_names=current_allowed_tool_names,
        turn_tool_history=turn_tool_history,
    )
    return coding_preflight_tool_calls or None


def _enforce_deterministic_artifacts(
    *,
    response: dict[str, Any],
    tool_calls: list[dict[str, Any]] | None,
    turn_tool_history: list[dict[str, Any]],
    current_allowed_tool_names: set[str],
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    # Binding, contract-independent rule: once the turn holds an AWS topology
    # or code-structure snapshot, freehand diagram XML from the model never
    # dispatches — the deterministic evidence renderer replaces it.
    from ._loop_evidence_diagrams import enforce_evidence_backed_diagrams

    enforced = enforce_evidence_backed_diagrams(
        tool_calls=tool_calls,
        turn_tool_history=turn_tool_history,
        allowed_tool_names=current_allowed_tool_names,
    )
    if enforced is not None:
        tool_calls, audit_trace = enforced
        response = {**response, "tool_calls": tool_calls}
        context_snapshot["evidence_diagram_enforcement"] = compact_trace_value(
            audit_trace, trace_limits=runtime_settings
        )
    return response, tool_calls


def _keep_model_workflow_tool_calls(
    *,
    response: dict[str, Any],
    tool_calls: list[dict[str, Any]] | None,
    workflow_id: str,
    workflow_contract: dict[str, Any],
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The model's own workflow-process calls without its other calls; None when it made no such call."""
    workflow_process_tools = _workflow_process_tool_names(workflow_contract)
    model_workflow_tool_calls = [
        call
        for call in (tool_calls or [])
        if isinstance(call, dict) and _tool_call_name(call) in workflow_process_tools
    ]
    if not model_workflow_tool_calls:
        return None
    dropped_tool_names = [
        _tool_call_name(call)
        for call in (tool_calls or [])
        if isinstance(call, dict) and _tool_call_name(call) not in workflow_process_tools
    ]
    if dropped_tool_names:
        response = {**response, "tool_calls": model_workflow_tool_calls}
        context_snapshot["workflow_orchestration"] = compact_trace_value(
            {
                "workflow_id": workflow_id,
                "artifact_type": workflow_contract.get("artifact_type"),
                "topic": workflow_contract.get("topic"),
                "kept_model_workflow_tool_names": [_tool_call_name(call) for call in model_workflow_tool_calls],
                "dropped_non_workflow_tool_names": dropped_tool_names,
            },
            trace_limits=runtime_settings,
        )
    return response, model_workflow_tool_calls


def _record_advisory_workflow_suggestion(
    *,
    workflow_id: str,
    workflow_contract: dict[str, Any],
    workflow_tool_calls: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
) -> None:
    context_snapshot["workflow_orchestration"] = compact_trace_value(
        {
            "workflow_id": workflow_id,
            "artifact_type": workflow_contract.get("artifact_type"),
            "topic": workflow_contract.get("topic"),
            "suggested_tool_names": [
                str((item.get("function") or {}).get("name") or "").strip()
                for item in workflow_tool_calls
                if isinstance(item, dict)
            ],
            "model_tool_names": [
                str((item.get("function") or {}).get("name") or "").strip()
                for item in (tool_calls or [])
                if isinstance(item, dict)
            ],
            "mode": "advisory_model_tool_preserved",
        },
        trace_limits=runtime_settings,
    )


def apply_workflow_response_override(
    *,
    request_analysis: dict[str, Any],
    response: dict[str, Any],
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    turn_tool_history: list[dict[str, Any]],
    covered_evidence_axes: set[str],
    current_allowed_tool_names: set[str],
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
    workflow_contract_from_request_analysis: Callable[[dict[str, Any]], dict[str, Any] | None],
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]],
) -> tuple[dict[str, Any], str, list[dict[str, Any]] | None, dict[str, Any], dict[str, Any] | None]:
    workflow_contract = workflow_contract_from_request_analysis(request_analysis)
    workflow_id = str((workflow_contract or {}).get("workflow_id") or "").strip()
    response, tool_calls = _enforce_deterministic_artifacts(
        response=response, tool_calls=tool_calls, turn_tool_history=turn_tool_history,
        current_allowed_tool_names=current_allowed_tool_names,
        context_snapshot=context_snapshot, runtime_settings=runtime_settings,
    )

    if not workflow_contract:
        return response, content, tool_calls, context_snapshot, workflow_contract
    if _workflow_planner_mode(workflow_contract) == "advisory":
        return response, content, tool_calls, context_snapshot, workflow_contract

    workflow_tool_calls = plan_next_workflow_tool_calls(
        workflow_contract,
        turn_tool_history=turn_tool_history,
        covered_evidence_axes=covered_evidence_axes,
        allowed_tool_names=current_allowed_tool_names,
    )
    if not workflow_tool_calls:
        return response, content, tool_calls, context_snapshot, workflow_contract

    kept_workflow_calls = _keep_model_workflow_tool_calls(
        response=response,
        tool_calls=tool_calls,
        workflow_id=workflow_id,
        workflow_contract=workflow_contract,
        context_snapshot=context_snapshot,
        runtime_settings=runtime_settings,
    )
    if kept_workflow_calls is not None:
        response, model_workflow_tool_calls = kept_workflow_calls
        return response, content, model_workflow_tool_calls, context_snapshot, workflow_contract

    if not tool_calls:
        return response, content, tool_calls, context_snapshot, workflow_contract

    _record_advisory_workflow_suggestion(
        workflow_id=workflow_id,
        workflow_contract=workflow_contract,
        workflow_tool_calls=workflow_tool_calls,
        tool_calls=tool_calls,
        context_snapshot=context_snapshot,
        runtime_settings=runtime_settings,
    )
    return response, content, tool_calls, context_snapshot, workflow_contract
