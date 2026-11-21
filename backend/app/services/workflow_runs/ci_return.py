"""After CI failed on the pushed commit, the fix phase must fix exactly that.

Without this: CI failed on lint (E501) and the ``ci.failed`` loop returned to implement. The model's fix was
refused, yet implement and green passed without any change, the review passed the same tree, and the push answered
"nothing to push" — a failure no one can retry, so the run ended ``blocked``.

**A pending CI failure** is the run's recorded CI result (``context.ci``) failed for the commit the run pushed last
(``context.head_sha``); the next push clears it. While one is pending:

1. **The fix phase must address it** (:func:`ci_fix_evidence`). A turn of the phase the ``ci.failed`` loop returns to
   gets the blocking check ``ci_findings_addressed``, bound to fresh evidence on the current copy — never to "the tree
   changed":
   - CI named failing tests: each of them passed in this turn's newest test run;
   - CI failed without a failing test (a lint or other step): the repository's declared lint command, run fresh on
     the copy (``declared_lint``), passes on the run's change; a linter that cannot start pauses the run
     ``environment_not_ready``;
   - neither can be verified (no failing test, no declared lint): the check fails — the platform cannot prove a fix.
   A failure gets the checks reminder naming the finding; the phase does not pass.
2. **A push with nothing new is no dead end** (``scm.push`` → :data:`CI_RETURN`). It returns to the fix phase through
   the same ``ci.failed`` loop edge, so the CI loop budget bounds it (its limit pauses as every loop does). A push
   with no change and no pending CI failure fails.
"""

from __future__ import annotations

from typing import Any

CI_FIX_CHECK = "ci_findings_addressed"
CI_RETURN = "ci_return"  # the route of a push that has nothing new while the pushed commit's CI failed
CI_FAILED_CONDITION = "ci.failed"
_FAILED_OUTCOMES = frozenset({"failed", "error"})
DESCRIPTION = "The CI failure of the pushed commit is fixed"


def pending_ci_failure(run: Any) -> dict[str, Any] | None:
    """The recorded CI result when it failed for the commit the run pushed last, else ``None``."""
    context = dict(getattr(run, "context", None) or {})
    ci = dict(context.get("ci") or {})
    head = str(context.get("head_sha") or "")
    return ci if ci.get("state") == "failed" and head and ci.get("sha") == head else None


def ci_return_edge(graph: Any) -> Any:
    """The loop edge a failed CI takes back to the fix phase, else ``None``."""
    return next((edge for edge in graph.edges if edge.when == CI_FAILED_CONDITION and edge.kind == "loop"), None)


def _failed_tests(ci: dict[str, Any]) -> list[str]:
    return sorted(test for test, outcome in dict(ci.get("tests") or {}).items() if outcome in _FAILED_OUTCOMES)


async def ci_fix_evidence(db: Any, run: Any, evidence: Any) -> dict[str, Any]:
    """``{"state": passed|failed, "reason"}`` for the pending CI failure on this turn's fresh evidence."""
    from .workspace.declared_lint import declared_lint_run, environment_failure

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
    lint = evidence.lint if evidence.lint is not None else await declared_lint_run(db, run)
    evidence.lint = lint
    evidence.environment_failure = evidence.environment_failure or environment_failure(lint)
    if lint is None:
        return {"state": "failed", "reason": f"CI failed{where} outside the tests and the repository declares no lint "
                                             "command the platform can re-run: the fix cannot be verified"}
    if lint.get("state") == "passed":
        return {"state": "passed", "reason": ""}
    return {"state": "failed", "reason": f"CI failed{where}; the declared lint still fails: "
                                         f"{lint.get('reason') or 'see its output'}"}


async def with_ci_fix(db: Any, checks: list[dict[str, Any]], evidence: Any, *,
                      request_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The turn's checks, plus ``ci_findings_addressed`` (evaluated into ``evidence.ci_fix``) when this is a turn of
    the phase a failed CI returned to and that failure is still pending."""
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
