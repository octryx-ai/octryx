"""The ``parallel_work`` scheduler: which items run, when the node is done, when it goes back (design section 3).

Every call holds the run claim. ``advance`` starts each ``pending`` item whose dependencies are all ``merged`` (in
plan order, within the executor's capacity; ``parallel: false`` runs one at a time), then decides the node:

- every item ``merged`` → ``done`` (the executor tidies up first: the server soft-resets to the base);
- nothing running or waiting for its merge, nothing that can start, and something ``failed``, ``blocked`` or in
  ``conflict`` → ``replan``: the way back to the coordinator, whose contract carries one finding per item that is not
  merged (the node's gate result, which the loop edge carries like a failed gate's).

The split itself lives in ``context.work`` (schema: ``teamwork/__init__``). An item's turn reports through
``item_finished``; a merge through ``merge_reported``. A transient model failure retries the item once by resuming
its own session (as the device continuation does); a turn that ends without passing is ``failed``.

**Never re-dispatch blindly** (otherwise the two ready items were started again
on every tick for three minutes — about 170 item sessions and 106 device jobs, nearly all rejected — because a started
item was never stored as ``running``):

- the split is stored as its own copy (:func:`_store`), so a start's ``running``, session and job always reach the
  database before the next tick;
- a refused start (the device turned the job down before the agent ran, or the platform could not start it) keeps
  the item's session and waits ``START_RETRY_SECONDS`` × 2^(n-1) before the next start of the same session; the
  ``MAX_START_REFUSALS``-th refusal makes it ``failed`` with the reason, which goes back to the coordinator;
- the run's ``node_state.work_wake_at`` names when a waiting item can start, so the device channel's check
  (:func:`advance_due`) starts it even when no job of the run ends.
"""

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
    choose_executor,
    count_refusal,
    executor_of,
    findings,
    ready,
    startable,
)

EVENT_ENTERED = "work_entered"
EVENT_ITEM = "work_item"
EVENT_ROUTE = "work_route"


def _store(run: Any, work: dict[str, Any]) -> None:
    """Store the split as its own copy. Otherwise storing the caller's dicts let the next
    in-place change (an item's ``running``, its session and job) reach the stored value too, so SQLAlchemy saw no
    change and never wrote it; every tick found the item ``pending`` and started it again."""
    work["updated_at"] = _now()
    run.context = {**dict(run.context or {}), WORK_KEY: copy.deepcopy(work)}


def _event(db: Any, run: Any, item: dict[str, Any], **detail: Any) -> None:
    record_event(db, run, EVENT_ITEM, node_id=run.current_node_id,
                 detail={"item": item.get("id"), "status": item.get("status"), "iteration": item.get("iteration"),
                         **({"reason": item["reason"]} if item.get("reason") else {}), **detail})


def _at_node(run: Any, work: dict[str, Any]) -> bool:
    return bool(work) and run.status == "running" and run.current_node_id == work.get("node_id") and not work.get(
        "route")


# --- the plan's split --------------------------------------------------------------------------------------------


async def enter(db: Any, run: Any, node: Any, *, graph: Any) -> str | None:
    """The engine entered the ``parallel_work`` node: build the split from the recorded plan and start it. Returns
    the route when the node is decided at once (everything already merged, or no plan), else ``None`` (the engine
    waits; the scheduler resolves the node later)."""
    from ..phase_outputs import recorded_output
    from .node import plan_node_id

    envelope = recorded_output(run, OUTPUT_KIND) or {}
    record = dict(envelope.get("record") or {})
    previous = work_of(run)
    work = {**previous, "node_id": node.id, "plan_node": plan_node_id(node), "route": None}
    if record:
        from .plan import revise

        current = dict(previous.get("items") or {}) if previous.get("node_id") == node.id else {}
        if previous.get("plan_version") != envelope.get("version") or not current:
            current = revise(current, record)
        work.update(items=current, plan_version=envelope.get("version"), plan_hash=envelope.get("hash"),
                    contract=record.get("contract") or "")
    work.setdefault("items", {})
    work["executor"] = await choose_executor(db, run)
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
    """The board identity of the coordinator on ``context.work`` (``teamwork.coordinator``), so the items'
    team block names whom to ask."""
    try:
        from .coordinator import fill_coordinator_hash as fill
    except ImportError:  # the board side is not part of this build
        return
    await fill(db, run)


# --- advancing -------------------------------------------------------------------------------------------------------


async def advance(db: Any, run: Any, *, resolve: bool = True) -> str | None:
    """Start what can start; resolve the node when nothing more can happen. The route taken, else ``None``."""
    work = work_of(run)
    if not _at_node(run, work):
        return None
    items = {key: dict(value) for key, value in dict(work.get("items") or {}).items()}
    executor = await executor_of(db, run, work)
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
        _store(run, work)  # the executor reads the split it starts from
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


async def _parallel(db: Any, run: Any, work: dict[str, Any], runs_parallel: Any) -> bool:
    from ..graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(str(work.get("node_id") or ""))
    return node is None or runs_parallel(node)


def _route(items: dict[str, dict[str, Any]]) -> str | None:
    statuses = [item.get("status") for item in items.values()]
    if statuses and all(status == MERGED for status in statuses):
        return ROUTE_DONE
    if any(status in (RUNNING, DONE) for status in statuses) or ready(items):
        return None  # something runs, or can start (now or once its retry time has come)
    return ROUTE_REPLAN  # stuck items, or pending ones that wait for a stuck dependency


async def advance_due(db: Any) -> list[str]:
    """Advance every running run whose waiting items' time has come (the device channel calls this on its check):
    an item after its backoff, or one that waited for a busy device whose slot freed for another run. The run ids
    advanced."""
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


def _gate(run: Any, work: dict[str, Any], lines: list[str]) -> None:
    """The node's result as a gate's, so the ``replan`` loop carries the findings to the coordinator's contract."""
    node_id = str(work.get("node_id") or "")
    run.gate_results = {**dict(run.gate_results or {}), node_id: {
        "state": "failed" if lines else "passed", "phase": None, "at": _now(),
        "results": [{"type": "work_item", "outcome": "failed", "blocking": True, "description": line}
                    for line in lines]}}


def _decide_replan(run: Any, work: dict[str, Any], lines: list[str]) -> str:
    _gate(run, work, lines)
    return ROUTE_REPLAN


def _mark(db: Any, run: Any, work: dict[str, Any], route: str) -> str:
    work["route"] = route
    _store(run, work)
    record_event(db, run, EVENT_ROUTE, node_id=work.get("node_id"), detail={"route": route})
    return route


async def _resolve(db: Any, run: Any, work: dict[str, Any], route: str) -> str:
    from ..engine import resolve_current_node

    _mark(db, run, work, route)
    await resolve_current_node(db, run, route, actor_id=None)
    return route


__all__ = ["advance", "advance_due", "enter"]
