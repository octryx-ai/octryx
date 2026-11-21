"""Workflow phases of ``handle_tool_followup``: the turn's contract, planned follow-up tools, post-tool outcome."""

from __future__ import annotations

from typing import Any

from app.services.workflow_contracts.artifact_contract import workflow_artifact_contract_satisfied
from app.services.workflow_contracts.registry import workflow_contract_from_request_analysis

from ...core.guards.tdd_cycle import is_tdd_cycle_complete, is_tdd_cycle_step
from ...core.turn.decision_timeline import append_quality_event
from ..request._loop_workflow import _workflow_process_tool_names
from ._loop_post_tool_inputs import PostToolInputs
from ._loop_tool_followup_inputs import ToolFollowupInputs, followup_result, sync_turn_trace_context


def _workflow_planner_mode(workflow_contract: dict[str, Any] | None) -> str:
    if not isinstance(workflow_contract, dict):
        return ""
    return str(workflow_contract.get("planner_mode") or "").strip().lower()


async def refresh_workflow_contract(run: ToolFollowupInputs) -> dict[str, Any] | None:
    """The turn's workflow contract as the tool round left it; the later phases plan from it. Never ends the turn."""
    run.workflow_contract = workflow_contract_from_request_analysis(run.request_analysis)
    return None


def _planned_workflow_tool_calls(run: ToolFollowupInputs) -> list[dict[str, Any]] | None:
    workflow_contract = run.workflow_contract
    if not (workflow_contract and _workflow_planner_mode(workflow_contract) != "advisory"):
        return None
    next_workflow_tool_calls = (
        []
        if run.workflow_artifact_ready_for_final_response
        else run.plan_next_workflow_tool_calls(
            workflow_contract,
            turn_tool_history=run.turn_tool_history,
            covered_evidence_axes=run.covered_evidence_axes,
            allowed_tool_names={*run.current_allowed_tool_names, *_workflow_process_tool_names(workflow_contract)},
        )
    )
    if next_workflow_tool_calls:
        return next_workflow_tool_calls
    if workflow_artifact_contract_satisfied(workflow_contract, turn_tool_history=run.turn_tool_history):
        run.workflow_artifact_ready_for_final_response = True
    return None


async def forced_tool_calls_outcome(run: ToolFollowupInputs) -> dict[str, Any] | None:
    forced_tool_calls = _planned_workflow_tool_calls(run)
    if not forced_tool_calls:
        return None
    append_quality_event(
        run.context_snapshot,
        title="Workflow planned follow-up tools",
        status="info",
        detail=f"Prepared {len(forced_tool_calls)} follow-up tool call(s).",
        metadata={
            "forced_tools": [
                str(call.get("function", {}).get("name") or call.get("tool_name") or "").strip()
                for call in forced_tool_calls
                if isinstance(call, dict)
            ],
        },
    )
    sync_turn_trace_context(run)
    return followup_result(
        run,
        "continue",
        forced_tool_calls=forced_tool_calls,
        workflow_artifact_ready_for_final_response=run.workflow_artifact_ready_for_final_response,
    )


async def _run_post_tool_outcome(run: ToolFollowupInputs) -> dict[str, Any]:
    return await run.handle_post_tool_outcome(PostToolInputs(
        db=run.db, session_id=run.session_id, runtime=run.runtime, response=run.response,
        request_messages=run.request_messages, context_snapshot=run.context_snapshot, tool_results=run.tool_results,
        current_user_message=run.current_turn_content, content=run.content, total_tokens_in=run.total_tokens_in,
        total_tokens_out=run.total_tokens_out, usage_model=run.usage_model, event_factory=run.event_factory,
        fetch_thread_context_state=run.fetch_thread_context_state,
        persist_synthesized_tool_assistant=run.persist_synthesized_tool_assistant,
        persist_traced_assistant_message=run.persist_traced_assistant_message,
        runtime_attempts=run.runtime_attempts, request_analysis=run.request_analysis,
        turn_tool_history=run.turn_tool_history, workflow_contract=run.workflow_contract,
        workflow_artifact_ready_for_final_response=run.workflow_artifact_ready_for_final_response,
        current_allowed_tool_names=run.current_allowed_tool_names, covered_evidence_axes=run.covered_evidence_axes,
        current_step=run.current_step, tdd_cycle_state=run.tdd_cycle_state, current_step_index=run.current_step_index,
        active_steps=run.active_steps, current_step_wrapup_forced=run.current_step_wrapup_forced,
        current_step_iterations=run.current_step_iterations,
        current_step_max_iterations=run.current_step_max_iterations, runtime_settings=run.runtime_settings,
        required_domains=run.required_domains, covered_summary_domains=run.covered_summary_domains,
        agent_definition=run.agent_definition, executed_tool_names=run.executed_tool_names,
        context_plan=run.context_plan, has_pending_approval_result=run.has_pending_approval_result,
        _has_awaiting_subagent_result=run._has_awaiting_subagent_result,
        _has_pending_clarification_result=run._has_pending_clarification_result,
        _latest_successful_tool_result_from_results=run._latest_successful_tool_result_from_results,
        _is_jira_sprint_planner=run._is_jira_sprint_planner,
        _build_jira_sprint_bundle_report=run._build_jira_sprint_bundle_report,
        format_repository_noop_sync_report=run.format_repository_noop_sync_report,
        format_repository_knowledge_sync_report=run.format_repository_knowledge_sync_report,
        format_recent_bitbucket_commits_report=run.format_recent_bitbucket_commits_report,
        build_iteration_ceiling_event=run.build_iteration_ceiling_event, plan_loop_recovery=run.plan_loop_recovery,
        stuck_loop_event=run.stuck_loop_event, is_tdd_cycle_step=is_tdd_cycle_step,
        is_tdd_cycle_complete=is_tdd_cycle_complete,
    ))


async def post_tool_followup_result(run: ToolFollowupInputs) -> dict[str, Any]:
    post_tool_outcome = await _run_post_tool_outcome(run)
    action = post_tool_outcome.get("action")
    append_quality_event(
        run.context_snapshot,
        title="Post-tool workflow outcome resolved",
        status="ok" if action in {"return", "advance_step", "append_system_message"} else "info",
        detail=f"Post-tool action: {action or 'continue'}.",
        metadata={"action": action, "workflow_artifact_ready": run.workflow_artifact_ready_for_final_response},
    )
    sync_turn_trace_context(run)
    advanced = action == "advance_step"
    current_step_index = post_tool_outcome.get("current_step_index", run.current_step_index)
    return {
        "action": action,
        "event": run.tool_event,
        "existing_thread_context": post_tool_outcome.get("existing_thread_context", run.existing_thread_context),
        "yield_content": post_tool_outcome.get("yield_content"),
        "yield_model": post_tool_outcome.get("yield_model", run.usage_model),
        "system_message": post_tool_outcome.get("system_message"),
        "followup_user_message": post_tool_outcome.get("followup_user_message"),
        "current_step_index": current_step_index,
        "current_step_iterations": post_tool_outcome.get("current_step_iterations", run.current_step_iterations),
        "current_step_tool_activity": post_tool_outcome.get(
            "current_step_tool_activity", run.current_step_tool_activity
        ),
        "current_step_wrapup_forced": post_tool_outcome.get(
            "current_step_wrapup_forced", run.current_step_wrapup_forced
        ),
        "step_tool_history": [] if advanced else run.step_tool_history,
        "step_tool_history_index": current_step_index if advanced else None,
        "workflow_artifact_ready_for_final_response": run.workflow_artifact_ready_for_final_response,
        "forced_tool_calls": post_tool_outcome.get("forced_tool_calls"),
        "repeated_previous_step_summary_count": run.repeated_previous_step_summary_count,
    }
