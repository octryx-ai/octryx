"""Phase outputs around a ``parallel_work`` node (``phase_outputs.submit_output``).

- An item's session records its result (``submit_phase_result``: ``done`` | ``blocked``) on its own item: several
  items end at the same time, so the run's single ``outputs.result`` slot would mix them up.
- The coordinator (any session of the run but an item's) may submit a revised ``work_plan`` while the items run; it is
  checked against the node's roles and the revision rules (a running item cannot change) and applied at once.
- A work plan submitted at its plan phase is checked against the roles of the ``parallel_work`` node it feeds.
- A re-plan after a red pipeline or the product owner's / review's answers must change the split:
  resubmitted unchanged, every item stays merged, ``work`` resolves ``done`` at once and the same
  red pipeline runs again, using up a loop for nothing.
"""

from __future__ import annotations

from typing import Any

from ....models import Session
from ..graph import NODE_PARALLEL
from . import ITEM_RESULT_VALUES, OUTPUT_KIND, RUNNING, item_key_of, session_works_on, work_of
from .node import plan_node_id, roles_of


def _refused(message: str, reason: str = "outside_phase_output") -> dict[str, Any]:
    return {"state": "refused", "reason": reason, "message": message}


async def parallel_submission(db: Any, run: Any, graph: Any, node: Any, spec: Any, raw: Any, *,
                              session_id: str | None) -> tuple[dict[str, Any] | None, Any]:
    """``(answer, node)``: an answer when the submission is settled here, else the node that accepts it."""
    from ..phase_outputs import RESULT_KIND
    from .item_results import record_result

    session = await db.get(Session, session_id) if session_id else None
    key = item_key_of(session)
    if key:
        item = dict(dict(work_of(run).get("items") or {}).get(key) or {})
        if item.get("status") != RUNNING or not session_works_on(run, {**item, "id": key}, session):
            return _refused(f"Item '{key}' is not running."), node
        if spec.kind != RESULT_KIND:
            return _refused(f"An item records only its result ({', '.join(ITEM_RESULT_VALUES)})."), node
        record, problems = spec.validate(raw if isinstance(raw, dict) else {})
        if not problems and record["value"] not in ITEM_RESULT_VALUES:
            problems = [f"value: one of {', '.join(ITEM_RESULT_VALUES)}"]
        if problems:
            return {"state": "refused", "reason": "invalid_output", "message": "; ".join(problems),
                    "problems": problems}, node
        record_result(run, key, record)
        return {"state": "recorded", "kind": RESULT_KIND, "item": key, "value": record["value"]}, node
    if spec.kind == OUTPUT_KIND and plan_node_id(node) in graph.nodes:
        return None, graph.nodes[plan_node_id(node)]  # the coordinator revises the plan while the items run
    return None, node


def _parallel_for(graph: Any, plan_id: str) -> Any:
    return next((candidate for candidate in graph.nodes.values()
                 if candidate.kind == NODE_PARALLEL and plan_node_id(candidate) == plan_id), None)


def plan_problems(run: Any, graph: Any, node: Any, record: dict[str, Any]) -> list[str]:
    """The plan against the roles of the node it feeds and against the items already running."""
    from .plan import revision_problems, validate_plan

    parallel = _parallel_for(graph, node.id) if node is not None else None
    problems: list[str] = []
    if parallel is not None:
        _record, problems = validate_plan(record, roles=roles_of(parallel))
    work = work_of(run)
    if work.get("items"):
        problems += revision_problems(dict(work["items"]), record)
        problems += _unchanged_replan(run, graph, node, dict(work["items"]), record)
    return problems


REPLAN_UNCHANGED = (
    "This re-plan comes from {why}, but the plan changes nothing: every item stays merged and the same change would "
    "be checked again. Reopen the item the failure lies in (reopen: true; a merged item whose instructions alone "
    "changed stays merged), add an item for what nobody built, or change the paths where a merge conflicted.")


def _unchanged_replan(run: Any, graph: Any, node: Any, items: dict[str, Any], record: dict[str, Any]) -> list[str]:
    """The plan pass the run is at came back from a red pipeline or a ``changed`` decision, and the plan is the
    split as it stands."""
    from .plan import changes_nothing

    why = _replan_cause(run, graph, node)
    return [REPLAN_UNCHANGED.format(why=why)] if why and changes_nothing(items, record) else []


def _replan_cause(run: Any, graph: Any, node: Any) -> str:
    """What sent the run back to this plan phase, when that must change the plan: ``""`` otherwise (the first pass,
    a replan from the items, or a revision while the items run)."""
    from ..graph import NODE_CONFIRMATION, NODE_PLATFORM_ACTION

    if node is None or run.current_node_id != node.id:
        return ""
    carried = dict(dict(dict(run.context or {}).get("carried") or {}).get(node.id) or {})
    source = graph.nodes.get(str(carried.get("from") or ""))
    if source is None:
        return ""
    if source.kind == NODE_PLATFORM_ACTION and str(source.config.get("action") or "") == "pipeline.run":
        return "a red pipeline"
    if source.kind == NODE_CONFIRMATION:
        return "the product owner's or the review's answers"
    return ""


__all__ = ["parallel_submission", "plan_problems"]
