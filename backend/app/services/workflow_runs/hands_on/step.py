"""The ``hands_on.run`` step: after the CI pipeline and before the review, the device starts the built app and runs the
platform's scenarios in a real browser (every pipeline and review can pass an app that loses its data on reload)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, WorkflowRun
from ....time_utils import utc_now
from ..graph import SUCCEEDED, PhasedNode
from ..platform.dispatch import ToolOutcome
from ..records import record_event

logger = logging.getLogger(__name__)


ACTION = "hands_on.run"
CONTEXT_KEY = "hands_on"
SCENARIOS_KEY = "hands_on_scenarios"
EVENT_REPORTED = "hands_on_reported"
CLASS_HANDS_ON_RED = "hands_on_red"
GENERATING, PENDING, GREEN, RED, SKIPPED = "generating", "pending", "green", "red", "skipped"
MODE_REPRODUCE = "reproduce"
# The time budget of a run's scenarios (Workspace ``config.hands_on.budget_seconds``): over it is a warning, over
# twice it the device stops running scenarios (those are red, "not run"), so the kept set cannot grow unnoticed.
BUDGET_SECONDS = 600


async def _project_setting(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    project = await db.get(Project, run.project_id) if run.project_id else None
    return dict(dict((project.config if project is not None else None) or {}).get("hands_on") or {})


REPRODUCE_KEY = "hands_on_reproduce"


def state(run: WorkflowRun) -> dict[str, Any]:
    context = dict(run.context or {})
    reproduce = dict(context.get(REPRODUCE_KEY) or {})
    if reproduce and reproduce.get("node_id") == run.current_node_id:
        return reproduce
    return dict(context.get(CONTEXT_KEY) or {})


def _set(run: WorkflowRun, value: dict[str, Any]) -> None:
    key = REPRODUCE_KEY if value.get("mode") == "reproduce" else CONTEXT_KEY
    run.context = {**dict(run.context or {}), key: value}


async def _switched_off(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> bool:
    if node.config.get("enabled") is False:
        return True
    return (await _project_setting(db, run)).get("enabled") is False


def _skip(db: AsyncSession, run: WorkflowRun, node: PhasedNode, reason: str) -> tuple[ToolOutcome, str]:
    reproduce = node.config.get("mode") == MODE_REPRODUCE
    _set(run, {"state": SKIPPED, "node_id": node.id, "reason": reason, "at": utc_now().isoformat(),
               **({"mode": MODE_REPRODUCE} if reproduce else {})})
    record_event(db, run, EVENT_REPORTED, node_id=node.id, detail={"state": SKIPPED, "reason": reason})
    return ToolOutcome(SUCCEEDED, {"skipped": reason}), SKIPPED if reproduce else SUCCEEDED


async def skipped(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> None:
    if node.config.get("mode") == MODE_REPRODUCE:
        from .reproduce import confirm_automatically

        await confirm_automatically(db, run)


async def start(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> tuple[ToolOutcome, str]:
    from ..pipeline import environment_file_for
    from ..platform_actions import WAIT
    from ..workspace.preparation import RUNTIME_SERVER, runtime_of

    if await _switched_off(db, run, node):
        return _skip(db, run, node, "switched off for this Workspace or workflow")
    if await runtime_of(db, run) == RUNTIME_SERVER:
        return _skip(db, run, node, "no browser for a server run")
    pointer = await environment_file_for(db, run)
    if pointer is None:
        return _skip(db, run, node, "the repository has no environment file to declare how the app is served")
    from ..workspace.contract_pin import pin

    declared = dict(dict(pin(run) or {}).get("environment") or {})
    if declared and not any(declared.get(key) for key in ("serve", "system_test", "browser")):
        return _skip(db, run, node, "the environment file declares no UI (no serve, system_test or browser)")
    reproduce = node.config.get("mode") == MODE_REPRODUCE
    if not reproduce and await _unchanged_since_red(db, run):
        return ToolOutcome("waiting", {"paused": "hands_on_unchanged"}), WAIT
    scenarios = list(dict(run.context or {}).get(SCENARIOS_KEY) or [])
    budget = (await _project_setting(db, run)).get("budget_seconds")
    from ..red_on_base import before_fix

    proof = before_fix(run, node, str(pointer.get("app_folder") or ".")) if reproduce else None
    _set(run, {"state": PENDING if scenarios or reproduce else GENERATING, "node_id": node.id,
               **({"red_on_base": proof} if proof else {}),
               "entry": dict(run.node_state or {}).get("entry"), "environment_file": pointer,
               "budget_seconds": budget if type(budget) is int and budget > 0 else BUDGET_SECONDS,
               **({"mode": MODE_REPRODUCE, "bug_key": run.ticket_key or ""} if reproduce else {}),
               "at": utc_now().isoformat()})
    if scenarios or reproduce:
        from ..octryx.continuation import runtime_step_entered

        await runtime_step_entered(db, run, node)
    return ToolOutcome("waiting", {"scenarios": len(scenarios) or "being written"}), WAIT


async def _unchanged_since_red(db: AsyncSession, run: WorkflowRun) -> bool:
    # The device's base recheck already judged this tree; the same code can only be red again.
    from ..limits import pause_run
    from ..pipeline import state as pipeline_state
    from ..run_texts import run_text
    from ..states import PAUSE_AGENT_LOOP

    previous, tree = state(run), str(pipeline_state(run).get("tree") or "")
    if previous.get("state") != RED or not tree or previous.get("red_tree") != tree or previous.get("unchanged_paused"):
        return False  # a person who retries after this pause gets the run they asked for
    _set(run, {**previous, "unchanged_paused": True})
    failed = "; ".join(f"{item.get('id')} {item.get('title') or ''}".strip()
                       for item in previous.get("results") or [] if isinstance(item, dict) and not item.get("passed"))
    await pause_run(db, run, reason=PAUSE_AGENT_LOOP, actor_id=None, detail={
        "code": "hands_on_unchanged", "resume": {"kind": "restart", "node_id": run.current_node_id},
        "message": run_text("hands_on.unchanged", failed=failed[:600] or "its scenarios")})
    return True


async def generate_due(db: AsyncSession, *, model_factory: Any = None) -> int:
    from ..states import STATUS_RUNNING
    from .scenario_job import generate

    runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.status == STATUS_RUNNING))).scalars().all()
    done = 0
    for run in runs:
        if state(run).get("state") != GENERATING or state(run).get("node_id") != run.current_node_id:
            continue
        try:
            done += int(await generate(db, run, model_factory=model_factory))
        except Exception:  # noqa: BLE001 - one run's failure never stops the others
            logger.exception("hands_on.generate_failed run_id=%s", run.id)
            await db.rollback()
    return done


CODE_SCENARIOS_FAILED = "hands_on_scenarios_failed"


def _pinned(run: WorkflowRun) -> dict[str, Any]:
    from ..workspace.contract_pin import view

    found = view(run)
    return {"environment_pin": found} if found else {}


def contract_view(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    if current.get("state") != PENDING:
        return None
    if current.get("mode") == MODE_REPRODUCE:
        return {"node_id": current.get("node_id"), "entry": current.get("entry"), "mode": MODE_REPRODUCE,
                "bug_key": current.get("bug_key"), "environment_file": current.get("environment_file"),
                "budget_seconds": current.get("budget_seconds"), "scenarios": [],
                **({"red_on_base": current["red_on_base"]} if current.get("red_on_base") else {}),
                **_pinned(run)}
    from ...engineering_knowledge.stacks import browser_start_seconds, hands_on_workers, restart_settle
    from ..build_cache import view as build_view
    from .waiver import waived

    skip = waived(run)
    return {"node_id": current.get("node_id"), "entry": current.get("entry"), **build_view(),
            **({"workers": workers} if (workers := hands_on_workers()) else {}),
            **({"browser_start_seconds": start} if (start := browser_start_seconds()) else {}),
            **({"restart_settle": settle} if (settle := restart_settle()) else {}),
            "environment_file": current.get("environment_file"), "budget_seconds": current.get("budget_seconds"),
            # Red regression scenarios run again on this commit; red there too is reported, never blocking.
            "base_sha": str(dict(run.context or {}).get("base_sha") or ""),
            "scenarios": [item for item in dict(run.context or {}).get(SCENARIOS_KEY) or []
                          if str(dict(item).get("id")) not in skip], **_pinned(run)}


def run_view(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    if not current:
        return None
    return {key: current.get(key) for key in ("state", "node_id", "reason", "problem", "reported_at", "results")
            if current.get(key) is not None}


def failure_for_agent(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    reproduce = dict(dict(run.context or {}).get(REPRODUCE_KEY) or {})
    if current.get("state") != RED and reproduce.get("state") == "repro_setup_failed":
        current = {**reproduce, "problem": reproduce.get("reason")}
    elif current.get("state") != RED:
        return None
    failed = [item for item in current.get("results") or [] if not item.get("passed")]
    return {"reason": current.get("problem") or "", "failed": failed[:12],
            "rule": ("The platform used the built app in a browser like a person would and these steps failed. Fix "
                     "the app (not the test): the same scenarios run again after your change.")}


async def record_report(db: AsyncSession, run: WorkflowRun, report: dict[str, Any], *, session_id: str) -> str:
    from .report import _record_reproduce, _route, _stale, record_interference, record_ran

    current = state(run)
    pass_key = (current.get("node_id"), current.get("entry"))
    if current.get("state") != PENDING or pass_key != (run.current_node_id, dict(run.node_state or {}).get(
            "entry")) or pass_key != (report.get("node_id"), report.get("entry")):
        return "ignored"
    if await _stale(db, run, current, report):
        return "ignored"
    from ..build_cache import record as record_builds

    record_builds(db, run, report)
    record_interference(db, run, report)
    outcome = str(report.get("state") or "")
    if current.get("mode") == MODE_REPRODUCE:
        return await _record_reproduce(db, run, current, report, session_id)
    if outcome == SKIPPED:
        reason = str(report.get("reason") or "the app declares no UI")[:300]
        _set(run, {**current, "state": SKIPPED, "reason": reason, "reported_at": utc_now().isoformat()})
        record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={"state": SKIPPED,
                                                                                   "reason": reason})
        await _route(db, run, ToolOutcome(SUCCEEDED, {"skipped": reason}))
        return SKIPPED
    return await record_ran(db, run, current, report, session_id=session_id, outcome=outcome)


def regenerate(db: AsyncSession, run: WorkflowRun, *, user_id: str, reason: str) -> int:
    from .waiver import WAIVED_KEY

    context = dict(run.context or {})
    dropped = len(list(context.get(SCENARIOS_KEY) or []))
    context.pop(SCENARIOS_KEY, None)
    context.pop(WAIVED_KEY, None)
    run.context = context
    current = state(run)
    if current.get("state") == PENDING and current.get("mode") != MODE_REPRODUCE:
        # The pass waiting now writes anew; a report the device was already running for the old set is stale.
        _set(run, {**current, "state": GENERATING, "at": utc_now().isoformat(), "stale_before": utc_now().isoformat()})
    record_event(db, run, "hands_on_scenarios_regenerated", node_id=run.current_node_id, actor_id=user_id,
                 detail={"dropped": dropped, "reason": reason[:500]})
    return dropped


__all__ = ["ACTION", "CONTEXT_KEY", "SCENARIOS_KEY", "contract_view", "failure_for_agent", "regenerate",
           "generate_due", "record_report", "run_view", "start", "state"]
