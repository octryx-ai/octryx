"""The device's hands-on report (``step.record_report``): a ran pass's verdict, a reproduce check, the routing."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from ..graph import FAILED, SUCCEEDED
from ..platform.dispatch import ToolOutcome
from ..records import record_event
from .results import repo_result, scenario_result
from .step import (
    ACTION,
    BUDGET_SECONDS,
    CLASS_HANDS_ON_RED,
    EVENT_REPORTED,
    GREEN,
    MODE_REPRODUCE,
    RED,
    SCENARIOS_KEY,
    _set,
)

EVENT_INTERFERENCE = "parallel_interference"
INTERFERENCE_ADVICE = ("this scenario failed while others ran at the same time and passed alone: the scenarios may "
                       "share the app's data; set \"parallel\": false in the environment file's serve to run them "
                       "one at a time")


def record_interference(db: AsyncSession, run: WorkflowRun, report: dict[str, Any]) -> None:
    for item in report.get("scenarios") or []:
        if isinstance(item, dict) and item.get("parallel_interference") is True:
            # Red side by side, green alone: information for the team, never red.
            record_event(db, run, EVENT_INTERFERENCE, node_id=run.current_node_id, detail={
                "scenario": str(item.get("id") or "")[:200], "advice": INTERFERENCE_ADVICE})


async def record_ran(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], report: dict[str, Any], *,
                     session_id: str, outcome: str) -> str:
    from .waiver import waived, waived_result

    skip = waived(run)
    scenarios = list(dict(run.context or {}).get(SCENARIOS_KEY) or [])
    by_id = {str(item.get("id")): item for item in report.get("scenarios") or [] if isinstance(item, dict)}
    results = [waived_result(item["id"], str(item.get("title") or ""), skip[item["id"]]) if item["id"] in skip
               else scenario_result(item, by_id.get(item["id"], {"error": "not run"})) for item in scenarios]
    # The repository's own scenarios (``tests/hands_on``: kept bug reproductions): each must pass too.
    titles = {str(item.get("id")): str(item.get("title") or "") for item in report.get("repo_scenarios") or []
              if isinstance(item, dict)}
    results += [waived_result(key, titles.get(key, key), skip[key]) if key in skip else repo_result(item, titles)
                for key, item in by_id.items() if key.startswith("repo:")]
    problem = str(report.get("problem") or "")[:1000] if outcome != "ran" else ""
    green = outcome == "ran" and bool(results) and all(item["passed"] for item in results)
    seconds = report.get("seconds") if isinstance(report.get("seconds"), int | float) else None
    over = bool(seconds and seconds > int(current.get("budget_seconds") or BUDGET_SECONDS))
    timing = {"seconds": seconds, **({"over_budget": current.get("budget_seconds") or BUDGET_SECONDS} if over else {})}
    from ..pipeline import state as pipeline_state

    tree = str(pipeline_state(run).get("tree") or "")
    _set(run, {**current, "state": GREEN if green else RED, "results": results, "reported_at": utc_now().isoformat(),
               "session_id": session_id, **({"problem": problem} if problem else {}), **timing,
               **({"red_tree": tree} if tree and not green else {})})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": GREEN if green else RED, **({"problem": problem} if problem else {}), **timing, **_serve_end(report),
        "scenarios": [{key: item[key] for key in ("id", "part", "title", "passed", "failed_step", "error",
                                                  "screenshots", "waived", "pre_existing", "invalid")
                       if key in item} for item in results]})
    from .invalid import record as record_invalid

    await record_invalid(db, run, results)
    if green:
        await _route(db, run, ToolOutcome(SUCCEEDED, {"scenarios": len(results)}))
        return GREEN
    failed = [f"{item['id']} {item['title']}: "
              + (" - ".join(str(part) for part in (item.get("failed_step"), item.get("error")) if part) or "failed")
              for item in results if not item["passed"]]
    reason = "hands-on red: " + "; ".join(([problem] if problem else []) + failed[:6])
    code = failure_code(report)
    if await _deterministic_pause(db, run, code, problem or reason):
        return RED
    from .. import failure_codes

    failure_codes.record(run, str(run.current_node_id), code=code, reason=reason)
    await _route(db, run, ToolOutcome(FAILED, {"results": results}, reason[:2000], failure_class=CLASS_HANDS_ON_RED))
    return RED


def _serve_end(report: dict[str, Any]) -> dict[str, Any]:
    end = report.get("serve_end")
    if not isinstance(end, dict):
        return {}
    return {"serve_end": {key: end.get(key) for key in ("by", "exit_code", "signal", "seconds")}}


def failure_code(report: dict[str, Any]) -> str:
    if str(report.get("code") or ""):
        return str(report["code"])[:60]
    items = [item for item in report.get("scenarios") or [] if isinstance(item, dict) and not item.get("passed")]
    if any(item.get("code") == "scenario_file_invalid" for item in items):
        return "scenario_file_invalid"
    return "scenario_step_failed" if items else "scenarios_failed"


async def _deterministic_pause(db: AsyncSession, run: WorkflowRun, code: str, problem: str) -> bool:
    # The same input fails the same way, so another loop round would only burn rounds.
    from .. import failure_codes
    from ..graph import graph_for_run
    from ..limits import pause_run
    from ..run_texts import run_text

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if not failure_codes.deterministic(code, dict(getattr(node, "config", None) or {})):
        return False
    failure_codes.record(run, str(run.current_node_id), code=code, reason=problem)
    reason = str(failure_codes.entry(code).get("pause_reason") or "needs_configuration")
    await pause_run(db, run, reason=reason, actor_id=None, detail={
        "code": code, "resume": {"kind": "restart", "node_id": run.current_node_id},
        "message": run_text("failure.deterministic", code=code, problem=problem[:800])})
    return True


async def _record_reproduce(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], report: dict[str, Any],
                            session_id: str) -> str:
    from ..graph import graph_for_run
    from ..red_on_base import environment_failure
    from ..red_on_base import record as record_base_run
    from .reproduce import record

    asked = current.get("red_on_base")
    failure = await environment_failure(db, run, asked, report.get("red_on_base"))
    record_base_run(run, asked, report.get("red_on_base"), node_id=str(run.current_node_id),
                    entry=current.get("entry"), environment=str((failure or {}).get("reason") or ""))
    if failure is not None:  # the device could not run the base: its problem, never a verdict on the reproduction
        from ..workspace.readiness import pause_not_ready

        _set(run, {**current, "state": "environment", "reason": failure["reason"], "session_id": session_id,
                   "reported_at": utc_now().isoformat()})
        await pause_not_ready(db, run, {**failure, "session_id": session_id})
        return "environment"

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    code = failure_code(report) if str(report.get("state") or "") != "ran" or any(
        isinstance(item, dict) and item.get("code") for item in report.get("scenarios") or []) else ""
    if code and await _deterministic_pause(db, run, code, str(report.get("problem") or code)):
        return "paused"
    state_name, route, reason = await record(db, run, dict(getattr(node, "config", None) or {}), report)
    if route == FAILED:
        from .. import failure_codes

        failure_codes.record(run, str(run.current_node_id), code=code or "scenario_step_failed", reason=reason)
    results = [repo_result(item, {}) for item in report.get("scenarios") or [] if isinstance(item, dict)]
    _set(run, {**current, "state": state_name, "results": results, "reason": reason, "session_id": session_id,
               "reported_at": utc_now().isoformat()})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": state_name, "mode": MODE_REPRODUCE, "reason": reason, **_serve_end(report),
        "scenarios": [{key: item[key] for key in ("id", "passed", "failed_step", "screenshots") if key in item}
                      for item in results]})
    await _route(db, run, ToolOutcome(SUCCEEDED if route != FAILED else FAILED, {"results": results}, reason,
                                      failure_class=CLASS_HANDS_ON_RED if route == FAILED else ""), route=route)
    return state_name


async def _route(db: AsyncSession, run: WorkflowRun, outcome: ToolOutcome, *, route: str = "") -> None:
    from ..engine import resolve_current_node
    from ..engine_context import _set_context
    from ..states import EVENT_ACTION

    node_id = run.current_node_id or ""
    route = route or (SUCCEEDED if outcome.ok else FAILED)
    _set_context(run, "actions", node_id, {"action": ACTION, "result": route, "reason": outcome.reason or None})
    _set_context(run, "action_ledger", f"{node_id}#{dict(run.node_state or {}).get('entry') or 0}",
                 {"action": ACTION, "result": route})
    record_event(db, run, EVENT_ACTION, node_id=node_id,
                 detail={"action": ACTION, "result": route, "reason": outcome.reason or None})
    await resolve_current_node(db, run, route, actor_id=None)


async def _stale(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], report: dict[str, Any]) -> bool:
    # A late report of an earlier pass would otherwise be keyed onto the new scenarios by id.
    from datetime import datetime, timedelta

    stale_before = str(current.get("stale_before") or "")
    if not stale_before:
        return False
    ids = {str(item.get("id")) for item in report.get("scenarios") or [] if isinstance(item, dict)
           and not str(item.get("id") or "").startswith("repo:")}
    wanted = {str(item.get("id")) for item in dict(run.context or {}).get(SCENARIOS_KEY) or []
              if isinstance(item, dict)}
    seconds = report.get("seconds") if isinstance(report.get("seconds"), int | float) else None
    try:
        started_early = seconds is not None and utc_now().replace(tzinfo=None) - timedelta(seconds=float(seconds)) < \
            datetime.fromisoformat(stale_before).replace(tzinfo=None)
    except ValueError:
        started_early = False
    if not started_early and (not ids or ids == wanted):
        return False
    record_event(db, run, "hands_on_report_stale", node_id=run.current_node_id,
                 detail={"reported": sorted(ids)[:20], "seconds": seconds, "stale_before": stale_before})
    from ..graph import graph_for_run
    from ..octryx.continuation import runtime_step_entered

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if node is not None:
        await runtime_step_entered(db, run, node)
    return True
