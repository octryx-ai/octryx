"""The ``parallel_work`` scheduler: which items run, when the node is done, when it goes back."""

from __future__ import annotations

import copy
from typing import Any

from ....time_utils import utc_now
from ..records import record_event
from . import DONE, MERGED, OUTPUT_KIND, PENDING, ROUTE_DONE, ROUTE_REPLAN, RUNNING, WORK_KEY, work_of
from .fix_rounds import _fix_red_pipeline, _fix_review, red_pipeline, review_to_fix
from .item_order import (
    WAKE_KEY,
    _now,
    _parse,
    _set_wake,
    count_refusal,
    executor_of,
    findings,
    ready,
    startable,
)
from .work_types import Route, SplitItem, WorkSplit

EVENT_ENTERED = "work_entered"
EVENT_ITEM = "work_item"
EVENT_ROUTE = "work_route"


def _store(run: Any, work: WorkSplit) -> None:
    # A copy: an in-place change of the caller's dicts would reach the stored value and SQLAlchemy would see no change.
    work["updated_at"] = _now()
    run.context = {**dict(run.context or {}), WORK_KEY: copy.deepcopy(work)}


def _event(db: Any, run: Any, item: SplitItem, **detail: Any) -> None:
    record_event(db, run, EVENT_ITEM, node_id=run.current_node_id,
                 detail={"item": item.get("id"), "status": item.get("status"), "iteration": item.get("iteration"),
                         **({"reason": item["reason"]} if item.get("reason") else {}), **detail})


def _at_node(run: Any, work: WorkSplit) -> bool:
    return bool(work) and run.status == "running" and run.current_node_id == work.get("node_id") and not work.get(
        "route")



async def enter(db: Any, run: Any, node: Any, *, graph: Any) -> Route | None:
    from ..phase_outputs import recorded_output
    from .node import plan_node_id

    envelope = recorded_output(run, OUTPUT_KIND) or {}
    record = dict(envelope.get("record") or {})
    previous = work_of(run)
    work: WorkSplit = {**previous, "node_id": node.id, "plan_node": plan_node_id(node), "route": None}
    if record:
        from .plan import revise

        current = dict(previous.get("items") or {}) if previous.get("node_id") == node.id else {}
        if previous.get("plan_version") != envelope.get("version") or not current:
            current = revise(current, record)
        work.update(items=current, plan_version=envelope.get("version"), plan_hash=envelope.get("hash"),
                    contract=record.get("contract") or "")
    work.setdefault("items", {})
    work["executor"] = (await executor_of(db, run)).name
    unchanged = bool(record) and previous.get("plan_version") == envelope.get("version")
    red = red_pipeline(run, graph, node.id, work) if unchanged else None
    unassigned = _fix_red_pipeline(db, run, work, red) if red is not None else []
    review = review_to_fix(run, graph, node.id, work) if unchanged and red is None else None
    if review is not None:
        unassigned = _fix_review(db, run, work, review)
    _store(run, work)
    await fill_coordinator_hash(db, run)
    work = work_of(run)
    record_event(db, run, EVENT_ENTERED, node_id=node.id,
                 detail={"plan_version": work.get("plan_version"), "executor": work["executor"],
                         "items": sorted(work["items"])})
    if not work["items"]:
        _decide_replan(run, work, ["No work plan was recorded: submit the plan with submit_work_plan."])
        return _mark(db, run, work_of(run), ROUTE_REPLAN)
    if unassigned:
        from .fixes import red_lines, review_lines

        _decide_replan(run, work, red_lines(unassigned) if red is not None else review_lines(unassigned))
        return _mark(db, run, work_of(run), ROUTE_REPLAN)
    return await advance(db, run, resolve=False)


async def fill_coordinator_hash(db: Any, run: Any) -> None:
    try:
        from .coordinator import fill_coordinator_hash as fill
    except ImportError:
        return
    await fill(db, run)



async def advance(db: Any, run: Any, *, resolve: bool = True) -> Route | None:
    # The caller holds the run claim (records.lock_run): two concurrent advances would start a ready item twice.
    work = work_of(run)
    if not _at_node(run, work):
        return None
    items: dict[str, SplitItem] = {key: dict(value) for key, value in dict(work.get("items") or {}).items()}
    executor = await executor_of(db, run)
    capacity = executor.capacity(run)
    from .node import runs_parallel

    if not await _parallel(db, run, work, runs_parallel):
        capacity = 1
    running = sum(1 for item in items.values() if item.get("status") == RUNNING)
    for key in startable(items):
        if capacity is not None and running >= capacity:
            break
        item = items[key]
        item["attempts"] = int(item.get("attempts") or 0) + 1
        work["items"] = items
        _store(run, work)
        updates = dict(await executor.start(db, run, dict(item)) or {})
        refused = updates.pop("refused", None)
        item.update(updates)
        if refused:
            count_refusal(item, str(refused))
        elif item.get("status") == RUNNING:
            running += 1
            item.update(started_at=_now(), finished_at=None, retry_at=None)
        elif item.get("status") == PENDING:
            item["attempts"] -= 1  # not started (a device slot is busy): no attempt used
        _event(db, run, item, executor=executor.name)
        items[key] = item
    work["items"] = items
    _store(run, work)
    _set_wake(run, items)
    route = _route(items)
    if route is None:
        return None
    if route == ROUTE_DONE:
        await executor.finish(db, run)
        work = work_of(run)
        _gate(run, work, [])
    else:
        _decide_replan(run, work, findings(items))
        work = work_of(run)
    return await _resolve(db, run, work, route) if resolve else _mark(db, run, work, route)


async def _parallel(db: Any, run: Any, work: WorkSplit, runs_parallel: Any) -> bool:
    from ..graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(str(work.get("node_id") or ""))
    return node is None or runs_parallel(node)


def _route(items: dict[str, SplitItem]) -> Route | None:
    statuses = [item.get("status") for item in items.values()]
    if statuses and all(status == MERGED for status in statuses):
        return ROUTE_DONE
    if any(status in (RUNNING, DONE) for status in statuses) or ready(items):
        return None
    return ROUTE_REPLAN


async def advance_due(db: Any) -> list[str]:
    from sqlalchemy import select

    from ....models import WorkflowRun
    from ..records import lock_run

    rows = (await db.execute(select(WorkflowRun.id, WorkflowRun.node_state).where(
        WorkflowRun.status == "running"))).all()
    now = utc_now()
    advanced = []
    for run_id, node_state in rows:
        wake = _parse(dict(node_state or {}).get(WAKE_KEY))
        if wake is None or wake > now:
            continue
        run = await lock_run(db, await db.get(WorkflowRun, run_id))
        await advance(db, run)
        advanced.append(run_id)
    return advanced


def _gate(run: Any, work: WorkSplit, lines: list[str]) -> None:
    node_id = str(work.get("node_id") or "")
    run.gate_results = {**dict(run.gate_results or {}), node_id: {
        "state": "failed" if lines else "passed", "phase": None, "at": _now(),
        "results": [{"type": "work_item", "outcome": "failed", "blocking": True, "description": line}
                    for line in lines]}}


def _decide_replan(run: Any, work: WorkSplit, lines: list[str]) -> Route:
    _gate(run, work, lines)
    return ROUTE_REPLAN


def _mark(db: Any, run: Any, work: WorkSplit, route: Route) -> Route:
    work["route"] = route
    _store(run, work)
    record_event(db, run, EVENT_ROUTE, node_id=work.get("node_id"), detail={"route": route})
    return route


async def _resolve(db: Any, run: Any, work: WorkSplit, route: Route) -> Route:
    from ..engine import resolve_current_node

    _mark(db, run, work, route)
    await resolve_current_node(db, run, route, actor_id=None)
    return route


__all__ = ["advance", "advance_due", "enter"]
