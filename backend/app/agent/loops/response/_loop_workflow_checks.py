"""A selected workflow's checks decide when a platform chat turn is done.

Runs where the final answer is accepted, after the answer evidence guard and the reply-contract check, for
the user-facing final answer of a turn whose explicitly selected workflow declares ``checks``
(``services/workflow_checks``): the current phase of the session's workflow run. It follows the answer evidence pattern with one difference: a turn is
never refused for a failed check.

- every blocking check passes: the answer is accepted, the record reads ``passed``;
- a blocking check fails for the first time: the answer is suppressed and the model gets the one reminder
  naming the failed checks (counted in the turn's own messages by its marker);
- it still fails after the reminder: the answer is accepted and recorded ``not_verified``.

Since A9 the workflow's required steps join the checks (``workflow_checks/steps``): a missing ``strict`` step
blocks and gets up to two reminders; a missing ``guided`` step gets one reminder and the turn continues.

Each accepted turn stores one ``workflow_check_results`` row and the record under ``workflow_checks`` in
the trace's context snapshot (the turn summary shows it). Nothing reads the user's prompt.

A turn an earlier guard **ends** never reaches this guard's acceptance, yet its checks are its result:
:func:`record_if_turn_ended` (any guard outcome ``return``) evaluates them on the turn's evidence without a reminder
and records them (``record_phase_turn`` for a run's phase). The terminal guards of ``handle_response_guards``:
transitions (diagram, transition and placeholder stops, the inline pseudo-tool-call refusal), coding (required step
tool / stalled step, no-evidence, analysis-only and narration stops), the follow-up stop, the answer evidence refusal
and the reply-contract stop. The withheld or stopped prose stays so; the run gets the phase result its submitted
outputs and tool calls earned.

Every record — accepted or ended — goes through :func:`_record`, which records **once per turn**
(``claim_turn_checks_record`` on the turn's binding): a later candidate of the same turn never reports a second time.
A reminder (``continue``) records nothing.

A phase turn whose required tool evidence already exists (:func:`phase_tool_evidence_present`: every blocking
``tool_called`` / ``evidence_count`` check of the phase passes on this turn's own calls) is not "intent only" for the
coding narration guard: its closing prose describes work it has done, and the phase's checks judge it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....services.answer_evidence.record import ANSWER_EVIDENCE_KEY
from ....services.prompt_catalog import render_prompt
from ....services.workflow_checks.evidence import turn_evidence
from ....services.workflow_checks.library import (
    PASSED,
    TOOL_CHECK_TYPES,
    describe_failed,
    evaluate_checks,
    failed_blocking,
    workflow_checks,
)
from ....services.workflow_checks.results import (
    RUNTIME_CHAT,
    WORKFLOW_CHECKS_KEY,
    check_record,
    check_state,
    store_check_result,
)
from ....services.workflow_checks.steps import MAX_STRICT_REMINDERS, STEP_GUIDED, STEP_STRICT, step_checks
from ....services.workflow_checks.test_commands import workspace_test_prefixes
from ....services.workflow_routing.workflow_selection import (
    ROUTING_RESOLUTION_KEY,
    workflow_selection_from_resolution,
)
from ....services.workflow_runs.binding import record_phase_turn, run_marker
from ...core.runtime.turn_execution_binding import claim_turn_checks_record

# The reminder carries this tag so the turn can count it in its own messages (one reminder only).
REMINDER_MARKER = "[workflow_checks_reminder]"
REMINDER_KEY = "workflow.checks.reminder"
STATE_REMINDED = "reminded"


def checks_reminder_count(messages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for message in messages or []
        if isinstance(message, dict)
        and str(message.get("role") or "") == "system"
        and str(message.get("content") or "").startswith(REMINDER_MARKER)
    )


def selected_workflow_checks(request_analysis: dict[str, Any] | None) -> tuple[str, list[dict[str, Any]]]:
    """``(workflow key, checks)`` of the turn's explicitly selected workflow; ``("", [])`` without one."""
    resolution = (request_analysis or {}).get(ROUTING_RESOLUTION_KEY)
    if not workflow_selection_from_resolution(resolution).selected:
        return "", []
    contract = resolution.get("workflow_contract")
    return str(resolution.get("workflow_key") or ""), [*workflow_checks(contract), *step_checks(contract)]


def _reminder_limit(checks: list[dict[str, Any]], results: list[Any]) -> int:
    """How many reminders the failures earn: two for a strict step, one otherwise, none when nothing failed."""
    failing = [check for check, result in zip(checks, results, strict=False) if result.outcome == "failed"]
    if any(check.get("step_mode") == STEP_STRICT for check in failing):
        return MAX_STRICT_REMINDERS
    reminded = [check for check in failing if check.get("blocking") is True or check.get("step_mode") == STEP_GUIDED]
    return 1 if reminded else 0


async def handle_workflow_checks_guard(
    *,
    db: Any,
    session_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
    request_messages: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    runtime_settings: dict[str, Any],
    usage_model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    has_followup_steps: bool,
    sub_agent_depth: int,
    request_analysis: dict[str, Any] | None,
    turn_tool_history: list[dict[str, Any]],
    persist_turn_trace: Callable[..., Any],
) -> dict[str, Any] | None:
    """``None`` accepts the reply (and records the result), else the loop outcome of the one reminder."""
    if tool_calls or has_followup_steps or sub_agent_depth > 0:
        return None
    workflow_key, checks = selected_workflow_checks(request_analysis)
    if not checks:
        return None
    evidence, checks, results = await _evaluate(db, session_id, checks, content=content,
                                                context_snapshot=context_snapshot, turn_tool_history=turn_tool_history,
                                                request_analysis=request_analysis)
    failed = failed_blocking(results) or [
        result for check, result in zip(checks, results, strict=False)
        if result.outcome == "failed" and check.get("step_mode") == STEP_GUIDED
    ]
    # A check the platform could not judge (unresolved test evidence) is no reminder for the agent: the run pauses.
    failed = [result for result in failed if not result.unresolved]
    # A test runner that could not start is the environment's, not the agent's: no reminder, the run pauses at once.
    environment_failed = bool(getattr(evidence, "environment_failure", None))
    if failed and not environment_failed and checks_reminder_count(messages) < _reminder_limit(checks, results):
        context_snapshot[WORKFLOW_CHECKS_KEY] = check_record(workflow_key, STATE_REMINDED, results, reminded=True)
        reminder = render_prompt(REMINDER_KEY, workflow_key=workflow_key, failed=describe_failed(failed))
        messages.append({"role": "assistant", "content": content or ""})
        messages.append({"role": "system", "content": f"{REMINDER_MARKER} {reminder}"})
        await persist_turn_trace(
            db=db, session_id=session_id, message_id=None, provider=runtime["provider_name"], model=usage_model,
            input_messages=request_messages, context_snapshot=context_snapshot, tool_trace=[],
            raw_output={"content": content, "tool_calls": [], "runtime_attempts": runtime_attempts,
                        "suppressed_for_workflow_checks": True},
            usage=response.get("usage", {}), trace_limits=runtime_settings,
        )
        await db.commit()
        return {"action": "continue"}
    await _record(db, session_id, workflow_key, results, evidence, context_snapshot=context_snapshot,
                  request_analysis=request_analysis, reminded=checks_reminder_count(messages) > 0)
    return None


async def record_checks_for_ended_turn(
    *,
    db: Any,
    session_id: str,
    messages: list[dict[str, Any]],
    context_snapshot: dict[str, Any],
    content: str,
    request_analysis: dict[str, Any] | None,
    turn_tool_history: list[dict[str, Any]],
    sub_agent_depth: int,
) -> None:
    """A turn a guard ended (its reply withheld or stopped): its checks' final verdict, recorded once, no reminder."""
    if sub_agent_depth > 0:
        return
    workflow_key, checks = selected_workflow_checks(request_analysis)
    if not checks:
        return
    evidence, checks, results = await _evaluate(db, session_id, checks, content=content,
                                                context_snapshot=context_snapshot, turn_tool_history=turn_tool_history,
                                                request_analysis=request_analysis)
    await _record(db, session_id, workflow_key, results, evidence, context_snapshot=context_snapshot,
                  request_analysis=request_analysis, reminded=checks_reminder_count(messages) > 0)


async def record_if_turn_ended(outcome: dict[str, Any] | None, **turn: Any) -> None:
    """Record the checks of a turn a guard ended (``action: return``); any other outcome records nothing."""
    if isinstance(outcome, dict) and outcome.get("action") == "return":
        await record_checks_for_ended_turn(**turn)


async def phase_tool_evidence_present(db: Any, session_id: str, *, request_analysis: dict[str, Any] | None,
                                      turn_tool_history: list[dict[str, Any]]) -> bool:
    """True for a workflow-run phase turn whose phase requires tool evidence (blocking ``tool_called`` /
    ``evidence_count`` checks) and every such check already passes on this turn's own tool calls."""
    if run_marker(request_analysis) is None:
        return False
    _workflow_key, checks = selected_workflow_checks(request_analysis)
    required = [check for check in checks if check.get("type") in TOOL_CHECK_TYPES - {"tool_not_called"}
                and check.get("blocking") is True]
    if not required:
        return False
    evidence = turn_evidence(turn_tool_history, test_command_prefixes=await workspace_test_prefixes(db, session_id))
    return all(result.outcome == PASSED for result in evaluate_checks(required, evidence))


async def _evaluate(db: Any, session_id: str, checks: list[dict[str, Any]], *, content: str,
                    context_snapshot: dict[str, Any], turn_tool_history: list[dict[str, Any]],
                    request_analysis: dict[str, Any] | None) -> tuple[Any, list[dict[str, Any]], list[Any]]:
    """``(evidence, effective checks, results)``: the checks the turn is judged by, with any the run adds."""
    from ....services.workflow_runs.ci_return import with_ci_fix
    from ....services.workflow_runs.workspace.declared_lint import declares_lint, with_turn_lint
    from ....services.workflow_runs.workspace.empty_copy import asks_for_reads, turn_workspace_empty

    evidence = turn_evidence(
        turn_tool_history, answer=content, answer_evidence=context_snapshot.get(ANSWER_EVIDENCE_KEY),
        test_command_prefixes=await workspace_test_prefixes(db, session_id),
    )
    if any(check.get("type") == "evidence_families" for check in checks):
        # The phase's evidence families are judged for the run's alert target and window.
        from ....services.workflow_checks.evidence_families import session_gate_scope

        evidence.alert_scope = await session_gate_scope(db, session_id)
    if declares_lint(checks):
        # The repository's declared lint, run fresh on the run's copy (a failure is the agent's reminder).
        evidence = await with_turn_lint(db, evidence, request_analysis=request_analysis)
    if asks_for_reads(checks):
        # An empty repository: nothing a read can succeed on; the run's working copy says so, never the agent.
        evidence.workspace_empty = await turn_workspace_empty(db, request_analysis=request_analysis)
    # After CI failed on the pushed commit, the fix phase passes only on fresh evidence that it is fixed.
    checks = await with_ci_fix(db, checks, evidence, request_analysis=request_analysis)
    return evidence, checks, evaluate_checks(checks, evidence)


async def _record(db: Any, session_id: str, workflow_key: str, results: list[Any], evidence: Any, *,
                  context_snapshot: dict[str, Any], request_analysis: dict[str, Any] | None, reminded: bool) -> None:
    if not claim_turn_checks_record(session_id):
        return  # this turn's result is already recorded: one record per turn, whichever path ended it
    state = check_state(results)
    context_snapshot[WORKFLOW_CHECKS_KEY] = check_record(workflow_key, state, results, reminded=reminded)
    await store_check_result(
        db, session_id=session_id, trace_id=None, workflow_key=workflow_key,
        workflow_version=None,
        runtime=RUNTIME_CHAT, state=state, results=results,
    )
    # A turn a workflow run governs reports its result to the run; only the run advances its phase.
    await record_phase_turn(db, request_analysis=request_analysis, session_id=session_id, state=state,
                            results=results, evidence=evidence)
    # Commit at once, like the answer evidence guard: the loop must not hold the write lock until the turn ends.
    await db.commit()


__all__ = ["REMINDER_MARKER", "checks_reminder_count", "handle_workflow_checks_guard", "phase_tool_evidence_present",
           "record_checks_for_ended_turn", "record_if_turn_ended", "selected_workflow_checks"]
