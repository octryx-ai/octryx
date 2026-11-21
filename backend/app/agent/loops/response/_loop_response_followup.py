"""Follow-up and artifact response guards for the standard loop.

``handle_followup_response_guards`` checks a reply without tool calls in a fixed order: missing evidence, an
incomplete TDD cycle or self review, and an unsatisfied workflow artifact contract each nudge the model and stop
the turn once the no-tool limit is reached.
"""

from __future__ import annotations

from typing import Any

from ....services.workflow_runs.phase_marker import is_run_phase_contract
from ..outcome._loop_evidence_completion import (
    build_missing_evidence_completion_reminder,
    missing_evidence_completion_action,
)
from ._loop_response_followup_artifact import unsatisfied_artifact_contract_guard
from ._loop_response_followup_inputs import (
    FollowupGuardInputs,
    _usable_model_draft,
    followup_result,
    remind_and_continue_or_stop,
)

_KNOWLEDGE_DETAIL_TOOL_NAMES = {
    "get_confluence_page",
    "knowledge_read",
    "knowledge_search",
    "search_confluence",
}


def _has_successful_knowledge_detail(turn_tool_history: list[dict[str, Any]]) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() not in _KNOWLEDGE_DETAIL_TOOL_NAMES:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if not result or result.get("error"):
            continue
        if any(result.get(key) for key in ("content", "summary", "excerpt", "title", "results", "items", "evidence")):
            return True
    return False


def _has_successful_knowledge_evidence(turn_tool_history: list[dict[str, Any]]) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() not in _KNOWLEDGE_DETAIL_TOOL_NAMES:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if result and not result.get("error"):
            return True
    return False


def _has_executed_knowledge_tool(executed_tool_names: set[str]) -> bool:
    return bool({str(name or "").strip() for name in executed_tool_names}.intersection(_KNOWLEDGE_DETAIL_TOOL_NAMES))


async def _missing_evidence_guard(run: FollowupGuardInputs) -> dict[str, Any] | None:
    missing_action = missing_evidence_completion_action(
        workflow_contract=run.workflow_contract,
        executed_tool_names=run.executed_tool_names,
        turn_tool_history=run.turn_tool_history,
    )
    if (
        run.tool_calls
        or missing_action is None
        or (_has_successful_knowledge_evidence(run.turn_tool_history) and _usable_model_draft(run.content))
    ):
        return None
    return await remind_and_continue_or_stop(
        run,
        reminder=build_missing_evidence_completion_reminder(missing_action),
        raw_output={
            "content": run.content,
            "tool_calls": [],
            "runtime_attempts": run.runtime_attempts,
            "suppressed_for_missing_evidence_completion": True,
            "missing_evidence_tool": missing_action.tool_name,
            "missing_evidence_label": missing_action.evidence_label,
        },
    )


async def _step_completion_guard(run: FollowupGuardInputs) -> dict[str, Any] | None:
    current_step = run.current_step
    raw_base = {"content": run.content, "tool_calls": [], "runtime_attempts": run.runtime_attempts}
    if (
        current_step
        and run.is_tdd_cycle_step(current_step)
        and not run.tool_calls
        and not run.is_tdd_cycle_complete(run.tdd_cycle_state)
    ):
        reminder = run.build_tdd_cycle_incomplete_reminder(
            current_step, run.tdd_cycle_state or run.build_initial_tdd_cycle_state()
        )
        return await remind_and_continue_or_stop(
            run,
            reminder=reminder,
            raw_output={
                **raw_base,
                "suppressed_for_incomplete_tdd_cycle": True,
                "tdd_cycle_state": run.tdd_cycle_state,
            },
        )
    if (
        current_step
        and run._is_self_review_step(current_step)
        and not run.tool_calls
        and not run._is_self_review_step_complete(current_step, run.step_tool_history)
    ):
        return await remind_and_continue_or_stop(
            run,
            reminder=run._build_incomplete_self_review_reminder(current_step),
            raw_output={**raw_base, "suppressed_for_incomplete_self_review": True},
        )
    return None


def _needs_artifact_contract_guard(run: FollowupGuardInputs, *, knowledge_detail_loaded: bool) -> bool:
    workflow_contract = run.workflow_contract
    return bool(
        workflow_contract
        and not run.tool_calls
        # A phase turn's completion reminder is the run's checks guard, never a family artifact nudge.
        and not is_run_phase_contract(workflow_contract)
        and not (run.workflow_id == "knowledge_request" and knowledge_detail_loaded)
        and not run.workflow_artifact_contract_satisfied(
            workflow_contract,
            turn_tool_history=run.turn_tool_history,
        )
    )


async def handle_followup_response_guards(run: FollowupGuardInputs) -> dict[str, Any]:
    """Guard a reply without tool calls against unfinished follow-ups; the counters in ``run`` are updated."""
    run.consecutive_coding_no_execution_count = 0
    knowledge_detail_loaded = run.workflow_id == "knowledge_request" and _has_successful_knowledge_detail(
        run.turn_tool_history
    )
    if (
        not run.tool_calls
        and (
            _has_successful_knowledge_evidence(run.turn_tool_history)
            or _has_executed_knowledge_tool(run.executed_tool_names)
        )
        and _usable_model_draft(run.content)
    ):
        return followup_result(run, "none")
    outcome = await _missing_evidence_guard(run)
    if outcome is not None:
        return outcome
    outcome = await _step_completion_guard(run)
    if outcome is not None:
        return outcome
    if _needs_artifact_contract_guard(run, knowledge_detail_loaded=knowledge_detail_loaded):
        return await unsatisfied_artifact_contract_guard(run, run.workflow_contract)
    return followup_result(run, "none")
