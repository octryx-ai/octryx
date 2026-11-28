"""A red pipeline or the review's open findings turned into targeted fix items of the split."""

from __future__ import annotations

from typing import Any

from ..records import record_event
from . import ROUTE_REPLAN

EVENT_FIX = "work_pipeline_fix"
EVENT_REVIEW_FIX = "work_review_fix"
FIXED_REVIEW_KEY = "fixed_review"
FIXED_KEY = "fixed_pipeline"


def review_to_fix(run: Any, graph: Any, node_id: str, work: dict[str, Any]) -> dict[str, Any] | None:
    from ..graph import NODE_CONFIRMATION
    from ..review.verdict import BLOCKING_SEVERITIES, verdict_from_record

    context = dict(run.context or {})
    carried = dict(dict(context.get("carried") or {}).get(node_id) or {})
    source = graph.nodes.get(str(carried.get("from") or "")) if graph is not None else None
    if source is None or source.kind != NODE_CONFIRMATION:
        return None
    answers = [dict(item) for item in context.get("po_answers") or [] if isinstance(item, dict)]
    marker = len(answers)
    if not answers or work.get(FIXED_REVIEW_KEY) == marker:
        return None
    verdict = verdict_from_record(context.get("review"))
    if not answers[-1].get("auto_revision") or verdict is None:
        return {"findings": [], "marker": marker, "why": "the product owner answered"}
    wanted = {"high"} if str(source.config.get("revise_on") or "") == "high" else {*BLOCKING_SEVERITIES, "high"}
    return {"findings": [item for item in verdict.findings if item.severity in wanted], "marker": marker}


def _fix_review(db: Any, run: Any, work: dict[str, Any], review: dict[str, Any]) -> list[str]:
    from .fixes import assign_review, reopen_for_fixes

    work[FIXED_REVIEW_KEY] = review["marker"]
    fixes, unassigned = assign_review(dict(work.get("items") or {}), review["findings"])
    if not review["findings"]:
        unassigned = [review.get("why") or "the review named nothing to fix"]
    if not unassigned and fixes:
        work["items"] = reopen_for_fixes(dict(work["items"]), fixes, source="review")
    record_event(db, run, EVENT_REVIEW_FIX, node_id=work.get("node_id"), detail={
        "items": sorted(fixes) if not unassigned else [], "unassigned": unassigned[:20],
        "route": "fix" if fixes and not unassigned else ROUTE_REPLAN})
    return unassigned


def red_pipeline(run: Any, graph: Any, node_id: str, work: dict[str, Any]) -> dict[str, Any] | None:
    from ..graph import NODE_PLATFORM_ACTION
    from ..pipeline import ACTION, STATE_RED, state

    carried = dict(dict(dict(run.context or {}).get("carried") or {}).get(node_id) or {})
    source = graph.nodes.get(str(carried.get("from") or "")) if graph is not None else None
    if source is None or source.kind != NODE_PLATFORM_ACTION or str(source.config.get("action") or "") != ACTION:
        return None
    red = state(run)
    if red.get("state") != STATE_RED or work.get(FIXED_KEY) == red.get("reported_at"):
        return None
    return red


def _fix_red_pipeline(db: Any, run: Any, work: dict[str, Any], red: dict[str, Any]) -> list[str]:
    from .fixes import assign, reopen_for_fixes

    fixes, unassigned = assign(dict(work.get("items") or {}), red)
    work[FIXED_KEY] = red.get("reported_at")
    if not unassigned and fixes:
        work["items"] = reopen_for_fixes(dict(work["items"]), fixes)
    record_event(db, run, EVENT_FIX, node_id=work.get("node_id"), detail={
        "items": sorted(fixes) if not unassigned else [], "unassigned": unassigned[:20],
        "route": "fix" if fixes and not unassigned else ROUTE_REPLAN})
    return unassigned or ([] if fixes else ["the pipeline is red, but no failing test or proof was reported"])
