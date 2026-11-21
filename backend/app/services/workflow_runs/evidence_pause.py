"""A TDD check the platform could not judge pauses the run ``evidence_unresolved``.

Example, on a device: the declared command's JUnit report keyed every result ``tests.test_textkit.test_x`` while the
confirmed tests were ``tests/test_textkit.py::test_x``; every confirmed test was "not seen", the red gate failed
three times on the platform's own mapping and the run paused at its loop limit with a follow-up issue. Ids are
canonical (``workflow_checks.test_ids``); what still cannot be keyed — a result whose file the run cannot
resolve, a report it cannot read, output listing fewer tests than its runner ran — is a platform/data problem, not
the agent's (``test_results.evidence_unresolved``):

- a gate whose blocking check failed only for that reason records its result and pauses here instead of taking its
  loop edge: no loop iteration, no failed-round comment, no follow-up issue;
- a phase turn reporting such a check pauses the same way before its result is applied;
- a paused run gets no automatic device continuation (``octryx.continuation`` starts only for a running run), and
  octryx-claude's Stop answers ``not_applicable`` so the session ends.

**Re-check** (``continue``) runs the evidence again: at a gate it re-enters the gate's phase (a
``pytest -q`` run names no passing test; re-reading the same runs could never resolve it, the phase's new pass runs
the corrected test command), a phase runs again as a new pass. Change plan and abort as usual.
"""

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
    """The hint after a concurrent run (``run.evidence.concurrent``): the stacks' evidence commands
    (``test_runner.evidence_args``), which the shell policy allows in every phase and whose output the platform
    attributes per test even when files run concurrently (policy and hint from the same data)."""
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
    """``True`` (and a ``check_uncertain`` note) when the checks failed only because the agent's own test output names
    no test the platform can attribute and a pipeline step comes after ``node_id``: the pipeline runs the tests itself
    with a per-test report (``stacks.json`` ``report_env``) and judges them there.

    A ``pytest -q | tail`` that names none of the tests must not pause a run whose fix is green: the agent's output
    format is never a reason to stop the run or to give it work."""
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
    """Pause the run at ``node_id`` for the blocking checks in ``results`` the platform could not judge."""
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
    """A run of concurrent test files with failures named only its failures: the agent's command, fixable by the
    agent. A pause ``evidence_unresolved`` would make a person
    re-check each time. Back into the phase with the hint in the contract instead (``test_evidence_hint``), at most
    ``MAX_RERUNS`` times per phase, then the pause."""
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
    """The hint for the phase's next pass after an automatic evidence re-run."""
    return dict(dict(dict(run.context or {}).get(RERUN_KEY) or {}).get(phase_id) or {}).get("hint") or None


async def _rerun_node(run: WorkflowRun, node_id: str, db: AsyncSession) -> str:
    """The node whose new pass produces fresh evidence: a gate's phase (its ``phase``, else the phase that leads into
    it, else the run's last phase), else the node itself. A gate like the bug flow's ``green``
    names no phase; a re-check at the gate would re-judge the same old run and pause again, a dead end."""
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
