"""Post-tool outcome handling for the standard agent loop.

``handle_post_tool_outcome`` runs the post-tool phases in a fixed order; the first phase that returns an action
dict ends the turn step. Phases live in ``_loop_post_tool_phases``, ``_loop_post_tool_gates``,
``_loop_post_tool_reports`` and ``_loop_post_tool_recovery``.
"""

from __future__ import annotations

from typing import Any

from ...core.guards.summary_domains import missing_summary_domains
from ._loop_capability_escalation import _capability_escalation_outcome
from ._loop_post_tool_gates import (
    _governed_coding_delivery_outcome,
    _missing_evidence_followup_outcome,
)
from ._loop_post_tool_inputs import PostToolInputs
from ._loop_post_tool_phases import (
    _PostToolEnv,
    _read_only_child_outcome,
)
from ._loop_post_tool_recovery import _iteration_ceiling_outcome, _stuck_loop_outcome
from ._loop_post_tool_reports import (
    _coding_completion_outcome,
    _jira_sprint_bundle_outcome,
    _single_tool_report_outcome,
)


def _post_tool_env(inputs: PostToolInputs) -> _PostToolEnv:
    return _PostToolEnv(
        db=inputs.db,
        session_id=inputs.session_id,
        runtime=inputs.runtime,
        response=inputs.response,
        request_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        tool_results=inputs.tool_results,
        current_user_message=inputs.current_user_message,
        content=inputs.content,
        usage_model=inputs.usage_model,
        runtime_settings=inputs.runtime_settings,
        runtime_attempts=inputs.runtime_attempts,
        request_analysis=inputs.request_analysis,
        turn_tool_history=inputs.turn_tool_history,
        workflow_contract=inputs.workflow_contract,
        post_tool_history=[*(inputs.turn_tool_history or []), *(inputs.tool_results or [])],
        persist_synthesized_tool_assistant=inputs.persist_synthesized_tool_assistant,
        persist_traced_assistant_message=inputs.persist_traced_assistant_message,
        fetch_thread_context_state=inputs.fetch_thread_context_state,
    )


async def _evidence_phases(inputs: PostToolInputs, env: _PostToolEnv) -> dict[str, Any] | None:
    outcome = await _capability_escalation_outcome(env) or await _governed_coding_delivery_outcome(
        env, current_step_iterations=inputs.current_step_iterations
    )
    if outcome is not None:
        return outcome
    outcome = await _read_only_child_outcome(env, current_allowed_tool_names=inputs.current_allowed_tool_names)
    if outcome is not None:
        return outcome
    return await _jira_sprint_bundle_outcome(
        env,
        agent_definition=inputs.agent_definition,
        current_step=inputs.current_step,
        current_step_index=inputs.current_step_index,
        active_steps=inputs.active_steps,
        latest_successful_tool_result_from_results=inputs._latest_successful_tool_result_from_results,
        is_jira_sprint_planner=inputs._is_jira_sprint_planner,
        build_jira_sprint_bundle_report=inputs._build_jira_sprint_bundle_report,
    )


async def _completion_phases(inputs: PostToolInputs, env: _PostToolEnv) -> dict[str, Any] | None:
    missing_domains = missing_summary_domains(inputs.required_domains, inputs.covered_summary_domains)
    outcome = _missing_evidence_followup_outcome(env, executed_tool_names=inputs.executed_tool_names)
    if outcome is not None:
        return outcome
    outcome = await _coding_completion_outcome(
        env,
        current_step=inputs.current_step,
        tdd_cycle_state=inputs.tdd_cycle_state,
        is_tdd_cycle_step=inputs.is_tdd_cycle_step,
        is_tdd_cycle_complete=inputs.is_tdd_cycle_complete,
    )
    if outcome is not None:
        return outcome
    has_followup_steps = inputs.current_step is not None and inputs.current_step_index < len(inputs.active_steps) - 1
    return await _single_tool_report_outcome(
        env,
        missing_domains=missing_domains,
        has_followup_steps=has_followup_steps,
        agent_definition=inputs.agent_definition,
        format_recent_bitbucket_commits_report=inputs.format_recent_bitbucket_commits_report,
    )


async def _recovery_phases(inputs: PostToolInputs, env: _PostToolEnv) -> dict[str, Any] | None:
    outcome = await _stuck_loop_outcome(
        env,
        stuck_loop_event=inputs.stuck_loop_event,
        current_step=inputs.current_step,
        current_step_index=inputs.current_step_index,
        active_steps=inputs.active_steps,
        current_step_wrapup_forced=inputs.current_step_wrapup_forced,
        plan_loop_recovery=inputs.plan_loop_recovery,
    )
    if outcome is not None:
        return outcome
    return await _iteration_ceiling_outcome(
        env,
        current_step=inputs.current_step,
        current_step_index=inputs.current_step_index,
        active_steps=inputs.active_steps,
        current_step_iterations=inputs.current_step_iterations,
        current_step_max_iterations=inputs.current_step_max_iterations,
        current_step_wrapup_forced=inputs.current_step_wrapup_forced,
        build_iteration_ceiling_event=inputs.build_iteration_ceiling_event,
        plan_loop_recovery=inputs.plan_loop_recovery,
    )


async def handle_post_tool_outcome(inputs: PostToolInputs) -> dict[str, Any]:
    """Resolve the loop action after a tool round."""
    if inputs.has_pending_approval_result(inputs.tool_results):
        return {"action": "return"}
    if inputs._has_awaiting_subagent_result(inputs.tool_results):
        return {"action": "return"}
    if inputs._has_pending_clarification_result(inputs.tool_results):
        return {"action": "return"}

    # Dead code (kept intentionally during the mechanical decomposition): this
    # block only ever executes `pass`, so it has no effect. Flagged for a
    # separate cleanup decision rather than silent deletion.
    workflow_contract = inputs.workflow_contract
    if workflow_contract:
        if (
            inputs.workflow_artifact_ready_for_final_response is False
            and workflow_contract
            and workflow_contract.get("artifact_path")
        ):
            pass

    env = _post_tool_env(inputs)
    for phases in (_evidence_phases, _completion_phases, _recovery_phases):
        outcome = await phases(inputs, env)
        if outcome is not None:
            return outcome
    return {"action": "none"}
