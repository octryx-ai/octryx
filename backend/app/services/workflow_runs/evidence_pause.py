"""A TDD check the platform could not judge pauses the run ``evidence_unresolved``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .states import PAUSE_EVIDENCE_UNRESOLVED

CONTEXT_KEY = "evidence_unresolved"
RERUN_KEY = "evidence_rerun"
EVENT_RERUN = "evidence_rerun"
MAX_RERUNS = 2
CONCURRENT_MARK = "the test files ran concurrently"


def concurrent_hint() -> str:
    from ..engineering_knowledge.stacks import evidence_commands
    from .run_texts import run_text

    commands = " or ".join(f"`{command}`" for command in evidence_commands())
    how = run_text("evidence.concurrent.with", commands=commands) if commands else \
        run_text("evidence.concurrent.one_file")
    return run_text("evidence.concurrent", how=how)


def _last_run(run: WorkflowRun) -> dict[str, Any]:
    from .test_resolution import recorded_runs

    runs = recorded_runs(run)
    return runs[-1] if runs else {}


async def deferred_to_pipeline(db: AsyncSession, run: WorkflowRun, results: list[Any], *, node_id: str) -> bool:
    # The agent's output format is never a reason to stop the run: the pipeline judges the tests per test.
    from . import uncertain
    from .graph import graph_for_run
    from .size_class.tests_scope import pipeline_later

    if not results or any(getattr(item, "type", "") == "evidence_families" for item in results):
        return False
    from .pipeline import STATE_GREEN

    # A pipeline that already ran green judged the tests from its own report (otherwise the review
    # gate after a green pipeline pauses on the agent's unattributable node output).
    green = str(dict(dict(run.context or {}).get("pipeline") or {}).get("state") or "") == STATE_GREEN
    if not green and not pipeline_later(await graph_for_run(db, run), node_id):
        return False
    uncertain.note(db, run, control=f"evidence:{node_id}", node_id=node_id, reason=(
        "the agent's test output named no test the platform could attribute; the pipeline after this step runs the "
        "tests with a per-test report and judges them: " + "; ".join(str(getattr(item, "detail", "")) for item in
                                                                         results)[:400]))
    return True


async def pause_unresolved(db: AsyncSession, run: WorkflowRun, results: list[Any], *, node_id: str) -> None:
    from .limits import pause_run

    checks = [{"type": result.type, "description": result.description, "detail": result.detail}
              for result in results if getattr(result, "unresolved", False)]
    last = _last_run(run)
    unresolved = [{key: item.get(key) for key in ("raw", "outcome", "reason")}
                  for item in last.get("unresolved") or [] if isinstance(item, dict)][:10]
    record = {"node_id": node_id, "entry": dict(run.node_state or {}).get("entry"), "checks": checks,
              "unresolved": unresolved, "problems": list(last.get("problems") or [])[:5],
              "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), CONTEXT_KEY: record}
    detail = "; ".join(str(check["detail"]) for check in checks)[:600]
    if await _rerun_concurrent(db, run, node_id, last, detail):
        return
    if any(check["type"] == "evidence_families" for check in checks):
        # An evidence source the alert's target needs could not answer; no "continue without it".
        message = (f"An evidence source the alert's target needs could not answer: {detail}. Nothing was counted "
                   "against the agent. Fix the source (connection, URL, credentials) and re-check, change the plan, "
                   "or abort.")
    else:
        message = (f"The platform could not match the test evidence to the confirmed tests: {detail}. Nothing was "
                   "counted against the agent. Next: re-check (the phase runs the tests again and the platform reads "
                   "them itself), or abort.")
    await pause_run(db, run, reason=PAUSE_EVIDENCE_UNRESOLVED, actor_id=None, detail={
        "message": message, "evidence": record, "resume": {"kind": "restart", "node_id": await _rerun_node(run, node_id,
                                                                                                    db)},
    })


async def _rerun_concurrent(db: AsyncSession, run: WorkflowRun, node_id: str, last: dict[str, Any],
                            detail: str) -> bool:
    from .engine import restart_at
    from .records import record_event

    if CONCURRENT_MARK not in " ".join(str(item) for item in last.get("problems") or []) + " " + detail:
        return False
    target = await _rerun_node(run, node_id, db)
    reruns = dict(dict(run.context or {}).get(RERUN_KEY) or {})
    used = int(dict(reruns.get(target) or {}).get("count") or 0)
    if used >= MAX_RERUNS:
        return False
    hint = concurrent_hint()
    reruns[target] = {"count": used + 1, "hint": hint, "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), RERUN_KEY: reruns}
    record_event(db, run, EVENT_RERUN, node_id=node_id, detail={"phase": target, "count": used + 1,
                                                                "limit": MAX_RERUNS, "hint": hint})
    await restart_at(db, run, target, actor_id=None)
    return True


def rerun_hint(run: WorkflowRun, phase_id: str) -> str | None:
    return dict(dict(dict(run.context or {}).get(RERUN_KEY) or {}).get(phase_id) or {}).get("hint") or None


async def _rerun_node(run: WorkflowRun, node_id: str, db: AsyncSession) -> str:
    # A gate names no phase; re-checking at the gate would re-judge the same run and pause again.
    from .graph import NODE_GATE, NODE_PHASE, graph_for_run

    graph = await graph_for_run(db, run)
    node = graph.nodes.get(node_id)
    if node is None or node.kind != NODE_GATE:
        return node_id
    phase = str(dict(getattr(node, "config", None) or {}).get("phase") or "")
    if phase:
        return phase
    sources = [edge.source for edge in graph.edges if edge.target == node_id
               and getattr(graph.nodes.get(edge.source), "kind", None) == NODE_PHASE]
    if len(sources) == 1:
        return sources[0]
    last = str(dict(run.context or {}).get("last_phase") or "")
    return last if last in graph.nodes else node_id


__all__ = ["CONTEXT_KEY", "RERUN_KEY", "pause_unresolved", "rerun_hint"]
