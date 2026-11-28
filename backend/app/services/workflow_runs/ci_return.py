"""After CI failed on the pushed commit, the fix phase must fix exactly that."""

from __future__ import annotations

from typing import Any

CI_FIX_CHECK = "ci_findings_addressed"
CI_RETURN = "ci_return"
CI_FAILED_CONDITION = "ci.failed"
_FAILED_OUTCOMES = frozenset({"failed", "error"})
DESCRIPTION = "The CI failure of the pushed commit is fixed"


def pending_ci_failure(run: Any) -> dict[str, Any] | None:
    context = dict(getattr(run, "context", None) or {})
    ci = dict(context.get("ci") or {})
    head = str(context.get("head_sha") or "")
    return ci if ci.get("state") == "failed" and head and ci.get("sha") == head else None


def ci_return_edge(graph: Any) -> Any:
    return next((edge for edge in graph.edges if edge.when == CI_FAILED_CONDITION and edge.kind == "loop"), None)


def _failed_tests(ci: dict[str, Any]) -> list[str]:
    return sorted(test for test, outcome in dict(ci.get("tests") or {}).items() if outcome in _FAILED_OUTCOMES)


async def ci_fix_evidence(db: Any, run: Any, evidence: Any) -> dict[str, Any]:
    ci = pending_ci_failure(run) or {}
    where = f" ({ci['url']})" if ci.get("url") else ""
    failed = _failed_tests(ci)
    if failed:
        last = dict((evidence.test_runs or [{}])[-1].get("results") or {}) if evidence.test_runs else {}
        open_ = [test for test in failed if dict(last.get(test) or {}).get("outcome") != "passed"]
        if not open_:
            return {"state": "passed", "reason": ""}
        return {"state": "failed", "reason": f"CI failed{where} on {', '.join(open_[:10])}: run these tests in this "
                                             "turn and make them pass"}
    # The server never re-runs a repository command, so a CI failure outside the tests stays unverified here.
    return {"state": "failed", "reason": f"CI failed{where} outside the tests and the platform cannot re-run it: "
                                         "the fix cannot be verified"}


async def with_ci_fix(db: Any, checks: list[dict[str, Any]], evidence: Any, *,
                      request_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    from ...models import WorkflowRun
    from .binding import run_marker
    from .graph import graph_for_run

    marker = run_marker(request_analysis)
    if marker is None or marker.get("slice"):
        return checks
    run = await db.get(WorkflowRun, str(marker["run_id"]))
    if run is None or pending_ci_failure(run) is None:
        return checks
    edge = ci_return_edge(await graph_for_run(db, run))
    if edge is None or edge.target != str(marker.get("node_id") or ""):
        return checks
    evidence.ci_fix = await ci_fix_evidence(db, run, evidence)
    return [*checks, {"type": CI_FIX_CHECK, "params": {}, "blocking": True, "description": DESCRIPTION}]


__all__ = ["CI_FIX_CHECK", "CI_RETURN", "ci_fix_evidence", "ci_return_edge", "pending_ci_failure", "with_ci_fix"]
