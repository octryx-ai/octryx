"""The device's pipeline report for the pending pass: judged green or red, recorded, and the step routed."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .graph import FAILED, SUCCEEDED
from .pipeline import ACTION, EVENT_REPORTED, STATE_GREEN, STATE_PENDING, STATE_RED, _set, state
from .pipeline_proofs import _pinned_file_audit, _record_test_runs, _tasks_after_pipeline
from .pipeline_results import _failed_line, _green, _judge_flaky, _results, _stored, _timings
from .platform.dispatch import ToolOutcome
from .records import record_event

EVENT_TIMED = "pipeline_timed"
CLASS_PIPELINE_RED = "pipeline_red"


async def record_report(db: AsyncSession, run: WorkflowRun, report: dict[str, Any], *, session_id: str) -> str:
    """The device's pipeline report for the pending pass; the state it established, or ``ignored``."""
    current = state(run)
    entry = dict(run.node_state or {}).get("entry")
    pass_key = (current.get("node_id"), current.get("entry"))
    if current.get("state") != STATE_PENDING or pass_key != (run.current_node_id, entry) or pass_key != (
            report.get("node_id"), report.get("entry")):
        return "ignored"
    if timings := _timings(report.get("timings")):
        # Where the device's pipeline time went, per step: measured, never derived again.
        current = {**current, "timings": timings}
        record_event(db, run, EVENT_TIMED, node_id=run.current_node_id, detail={"timings": timings})
    from .build_cache import record as record_builds

    record_builds(db, run, report)
    commands = list(current.get("commands") or [])
    audit: dict[str, Any] = {"source": "repository_record"}
    if current.get("environment_file"):
        audit = _pinned_file_audit(run, current, report)
        if audit["file_state"] != "ok":
            return await _file_red(db, run, current, audit, report, session_id=session_id)
        commands = list(audit["commands"])
        current["commands"] = commands
    results = _results(report, commands)
    ran = [item["command"] for item in results]
    from .task_list import run_task_list, unproven

    tasks = run_task_list(run)
    flaky = _judge_flaky(run, results)
    seen = _record_test_runs(run, results, tasks)
    suites_green = bool(results) and ran == commands and all(_green(item) for item in results)
    missing_proofs = unproven(tasks, seen) if tasks else []
    style_errors, style_warnings = _style(current, report)
    clean = suites_green and not missing_proofs and not style_errors
    paused, base_errors = await _red_on_base(db, run, current, audit, results, report, entry=entry, clean=clean,
                                             session_id=session_id)
    if paused is not None:
        return paused
    green = clean and not base_errors
    if not green and (paused := await _environment_red(db, run, current, audit, results, report,
                                                       session_id=session_id)) is not None:
        return paused  # also with style errors: an environment that cannot run a command comes first
    if tasks:
        await _tasks_after_pipeline(db, run, tasks, missing_proofs, green=green)
    stored = [_stored(item) for item in results]
    again = sorted({test for item in results for test in item.get("flaky_again") or []})
    from .pipeline_head import binding

    bound = await binding(run, report.get("tree"))  # the tree it ran on, the server's own (``pipeline_head``)
    audit = _audit(audit, ran, report, bound)
    _store_report(db, run, current, results, stored, green=green, missing_proofs=missing_proofs, bound=bound,
                  audit=audit, flaky=flaky, again=again, style_errors=style_errors, style_warnings=style_warnings,
                  base_errors=base_errors, session_id=session_id)
    outcome = await _outcome(db, run, results, commands, ran, stored, green=green, flaky=flaky,
                             missing_proofs=missing_proofs, style_errors=style_errors, base_errors=base_errors,
                             bound=bound)
    await _route(db, run, outcome)
    return STATE_GREEN if green else STATE_RED


async def _red_on_base(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], audit: dict[str, Any],
                       results: list[dict[str, Any]], report: dict[str, Any], *, entry: Any, clean: bool,
                       session_id: str) -> tuple[str | None, list[str]]:
    """The confirmed tests' run on the base commit: ``(state when the run paused instead, errors for the agent)``."""
    from .red_on_base import environment_failure as base_environment
    from .red_on_base import judge as red_on_base
    from .red_on_base import record as record_base_run

    base_failure = await base_environment(db, run, current.get("red_on_base"), report.get("red_on_base"))
    record_base_run(run, current.get("red_on_base"), report.get("red_on_base"), node_id=str(run.current_node_id),
                    entry=entry, environment=str((base_failure or {}).get("reason") or ""))
    if base_failure is not None and clean:
        return await _environment_pause(db, run, current, audit, results, report, base_failure,
                                        session_id=session_id), []
    # A base run the environment could not do says nothing about the change: never a reason sent to the agent.
    base_errors = [] if base_failure else red_on_base(current.get("red_on_base"), report.get("red_on_base"))
    from .red_on_base_proof import missing as missing_base_proof

    base_errors += missing_base_proof(run, current.get("red_on_base"))
    from .red_on_base import unattributed

    gap = [] if base_failure or base_errors else unattributed(current.get("red_on_base"), report.get("red_on_base"))
    if gap and clean:
        # The base run showed no result the platform could attribute: its own gap, one pause with cause platform,
        # never a round for the agent (otherwise three red pipelines on the same tree).
        from .red_on_base import no_test_started
        from .red_on_base_proof import pause_unattributed

        why = no_test_started(report.get("red_on_base"))
        return await _environment_pause(db, run, current, audit, results, report, {
            "reason": why or f"no base-commit result the platform could attribute: {', '.join(gap[:5])}"},
            session_id=session_id, pause=lambda: pause_unattributed(db, run, gap, why=why)), base_errors
    return None, base_errors


async def _environment_red(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], audit: dict[str, Any],
                           results: list[dict[str, Any]], report: dict[str, Any], *, session_id: str) -> str | None:
    """The run paused because the environment could not run a red command; ``None`` when the change is red."""
    from .pipeline_environment import environment_failure

    failure = await environment_failure(db, run, [item for item in results
                                                  if not _green(item) and not item.get("skipped")])
    if failure is not None:
        return await _environment_pause(db, run, current, audit, results, report, failure,
                                        session_id=session_id)
    return None


def _store_report(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], results: list[dict[str, Any]],
                  stored: list[dict[str, Any]], *, green: bool, missing_proofs: list[str], bound: dict[str, Any],
                  audit: dict[str, Any], flaky: list[str], again: list[str], style_errors: list[str],
                  style_warnings: list[str], base_errors: list[str], session_id: str) -> None:
    """The pass's pipeline state on the run and its ``pipeline_reported`` event."""
    _set(run, {**current, "state": STATE_GREEN if green else STATE_RED, "results": stored, "audit": audit,
               "unproven": missing_proofs, "reported_at": utc_now().isoformat(), "session_id": session_id,
               **({"code_style_errors": style_errors} if style_errors else {}),
               **({"code_style_warnings": style_warnings} if style_warnings else {}),
               "red_on_base_errors": base_errors, **bound, **({"flaky": flaky, "flaky_again": again} if flaky else {})})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": STATE_GREEN if green else STATE_RED, "unproven": missing_proofs, **bound, "audit": audit,
        **({"red_on_base": base_errors or "every confirmed test fails on the base"}
           if current.get("red_on_base") else {}),
        **({"flaky": flaky, "flaky_again": again} if flaky else {}),
        # Why a pass with green exits is red, on record (otherwise a pass red from its code
        # style alone had an event that did not say so).
        **({"code_style_errors": style_errors[:10]} if style_errors else {}),
        **({"red_on_base_errors": base_errors[:10]} if base_errors else {}),
        "commands": [{"command": item["command"], "exit_code": item["exit_code"], "seconds": item["seconds"],
                      **({"skipped": item["skipped"]} if item.get("skipped") else {}),
                      **({"rerun_exit_code": item["rerun"]["exit_code"], "rerun_tests": item["rerun"]["tests"]}
                         if item.get("rerun") else {})}
                     for item in results]})


async def _outcome(db: AsyncSession, run: WorkflowRun, results: list[dict[str, Any]], commands: list[str],
                   ran: list[str], stored: list[dict[str, Any]], *, green: bool, flaky: list[str],
                   missing_proofs: list[str], style_errors: list[str], base_errors: list[str],
                   bound: dict[str, Any]) -> ToolOutcome:
    """The step's outcome: green goes on (its verified commands remembered), red goes back with every reason."""
    if green:
        from .run_memory import pipeline_green as remember_green

        await remember_green(db, run, results)  # the app's verified commands, for the next run (run memory)
        note = (f"pipeline green; flaky, not counted this time (failed, then passed on a re-run with no change): "
                f"{', '.join(flaky)}") if flaky else ""
        return ToolOutcome(SUCCEEDED, {"results": stored, **({"flaky": flaky} if flaky else {})}, note)
    missing = [command for command in commands if command not in ran]
    failed = [_failed_line(item) for item in results if not _green(item)]
    # Code style first: otherwise the agent fixed the test failures it read first and grew the
    # oversized file again in every round.
    reasons = ["code style: " + "; ".join(style_errors[:12])] if style_errors else []
    reasons += [*failed, *(f"{command} did not run" for command in missing)]
    if missing_proofs:
        reasons.append("missing proof tests: " + ", ".join(missing_proofs))
    reasons += base_errors
    from .corrections import pipeline_red

    await pipeline_red(db, run, style_errors=style_errors, failed=failed, missing_proofs=missing_proofs,
                       base_errors=base_errors, tree=str(bound.get("tree") or ""))
    return ToolOutcome(FAILED, {"results": stored, "unproven": missing_proofs},
                       "pipeline red: " + "; ".join(reasons), failure_class=CLASS_PIPELINE_RED)


def _style(current: dict[str, Any], report: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The change's code style errors and warnings, from the device's counts against the run's base
    (``code_style.check``); none when the pipeline was started without a style or the device sent no counts."""
    from app.services.code_style.l10n_check import l10n_findings
    from app.services.code_style.tool_check import tool_findings

    from ..code_style.check import findings

    if not current.get("code_style") or not isinstance(report.get("sizes"), dict):
        return [], []
    style = dict(current["code_style"])
    found = [*findings(style, report["sizes"]), *tool_findings(report.get("style_tools"), style),
             *l10n_findings(style, report.get("l10n"))]
    return ([item.text() for item in found if item.severity == "error"],
            [item.text() for item in found if item.severity == "warning"])


def style_verdict(run: WorkflowRun, report: dict[str, Any]) -> dict[str, Any]:
    """Fail fast: the device asks before the system test whether the change's code
    style is red. Judged here by the same rules as the report (``_style``: old debt and info-only lint lines stay
    warnings), so the style verdict lives in one place; the device only skips the expensive command on ``blocking``.
    Read only: nothing is recorded; the pass's report is judged again as always. A report for another pass, or a pass
    without a style, is never blocking."""
    current = state(run)
    entry = report.get("entry")
    pass_key = (current.get("node_id"), current.get("entry"))
    if current.get("state") != STATE_PENDING or pass_key != (run.current_node_id, entry) or pass_key != (
            report.get("node_id"), entry):
        return {"blocking": False, "reason": "not_this_pass"}
    errors, _warnings = _style(current, report)
    return {"blocking": bool(errors), "errors": errors[:20]}


def _audit(audit: dict[str, Any], ran: list[str], report: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    """Which commands ran, from which declaration, on which commit and tree (the device's ``head`` and ``tree``, the
    server's own tree from ``pipeline_head``)."""
    head = str(report.get("head") or "")[:64]
    tree = str(report.get("tree") or "")[:64]
    return {**audit, "commands": ran, **({"head": head} if head else {}), **({"device_tree": tree} if tree else {}),
            **({"tree": bound["tree"]} if bound.get("tree") else {})}


async def _file_red(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], audit: dict[str, Any],
                    report: dict[str, Any], *, session_id: str) -> str:
    """Red without running anything: the environment file is missing, invalid, or its setup failed."""
    from .pipeline_head import binding

    bound = await binding(run, report.get("tree"))
    audit = _audit(audit, [], report, bound)
    _set(run, {**current, "state": STATE_RED, "results": [], "unproven": [], "audit": audit,
               "reported_at": utc_now().isoformat(), "session_id": session_id, **bound})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": STATE_RED, "audit": audit, "commands": [], **bound})
    errors = "; ".join(audit.get("file_errors") or [])
    reason = f"pipeline red: environment file {audit.get('file')} {audit.get('file_state')}" + (
        f": {errors}" if errors else "")
    await _route(db, run, ToolOutcome(FAILED, {"audit": audit}, reason[:2000], failure_class=CLASS_PIPELINE_RED))
    return STATE_RED


async def _environment_pause(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], audit: dict[str, Any],
                             results: list[dict[str, Any]], report: dict[str, Any], failure: dict[str, Any], *,
                             session_id: str, pause: Any = None) -> str:
    """Red because the environment could not run a command (``pipeline_environment``): the run pauses
    ``environment_not_ready`` at this step; no fix round, no loop iteration, no size escalation."""
    from .pipeline_head import binding
    from .workspace.readiness import pause_not_ready

    bound = await binding(run, report.get("tree"))
    audit = _audit(audit, [item["command"] for item in results], report, bound)
    stored = [_stored(item) for item in results]
    _set(run, {**current, "state": STATE_RED, "results": stored, "unproven": [], "audit": audit,
               "environment": failure["reason"], "reported_at": utc_now().isoformat(), "session_id": session_id,
               **bound})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": STATE_RED, "unproven": [], **bound, "audit": audit, "environment": failure["reason"],
        "commands": [{"command": item["command"], "exit_code": item["exit_code"], "seconds": item["seconds"]}
                     for item in results]})
    from .run_memory import environment_failed

    environment_failed(run, failure)  # kept with what ran past it once a pipeline is green (run memory)
    if pause is not None:
        await pause()  # another cause than the environment (the platform's evidence gap)
    else:
        await pause_not_ready(db, run, {**failure, "session_id": session_id})
    return STATE_RED


async def _route(db: AsyncSession, run: WorkflowRun, outcome: ToolOutcome) -> None:
    """Route the waiting node as ``run_platform_action`` would have (ledger, event); red is no failure pause:
    the definition's ``failed`` edge sends the work back to the agent."""
    from .engine import resolve_current_node
    from .engine_context import _set_context
    from .states import EVENT_ACTION

    node_id = run.current_node_id or ""
    route = SUCCEEDED if outcome.ok else FAILED
    _set_context(run, "actions", node_id, {"action": ACTION, "result": route, "reason": outcome.reason or None})
    _set_context(run, "action_ledger", f"{node_id}#{dict(run.node_state or {}).get('entry') or 0}",
                 {"action": ACTION, "result": route})
    record_event(db, run, EVENT_ACTION, node_id=node_id,
                 detail={"action": ACTION, "result": route, "reason": outcome.reason or None})
    await resolve_current_node(db, run, route, actor_id=None)
