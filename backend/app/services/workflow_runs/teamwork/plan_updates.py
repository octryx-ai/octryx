"""The coordinator's plan recorded or revised while the run is at its ``parallel_work`` node."""

from __future__ import annotations

from typing import Any

from . import OUTPUT_KIND, scheduler, work_of
from .scheduler import _at_node, _store, fill_coordinator_hash


async def plan_recorded(db: Any, run: Any, record: dict[str, Any], *, session_id: str | None) -> None:
    """A work plan was recorded: the run's task list becomes one task per item (the stored list wins, so the
    pipeline's "every task proven" and the reviewer's rules apply unchanged), the submitting session is the
    coordinator, and a plan revised while the items run is applied at once."""
    from .. import task_status
    from ..task_list import CONTEXT_KEY
    from .item_definition import item_task

    known = {str(task.get("id")): task for task in dict(run.context or {}).get(CONTEXT_KEY) or []
             if isinstance(task, dict)}
    tasks = []
    for item in record.get("items") or []:
        task = item_task(item)
        status = dict(known.get(task["id"]) or {}).get("status")
        tasks.append({**task, **({"status": status} if status and not item.get("reopen") else {})})
    await task_status.store(db, run, tasks)
    work = work_of(run)
    if session_id:
        work["coordinator_session_id"] = session_id
        _store(run, work)
    await fill_coordinator_hash(db, run)
    await plan_revised(db, run)


async def plan_revised(db: Any, run: Any) -> None:
    """The coordinator submitted a revised plan while the items run: apply it and go on (``revision_problems``
    already refused changing a running item)."""
    from ..phase_outputs import recorded_output
    from .plan import revise

    work = work_of(run)
    envelope = recorded_output(run, OUTPUT_KIND) or {}
    if not _at_node(run, work) or not envelope.get("record") or work.get("plan_version") == envelope.get("version"):
        return
    work.update(items=revise(dict(work.get("items") or {}), dict(envelope["record"])),
                plan_version=envelope.get("version"), plan_hash=envelope.get("hash"),
                contract=dict(envelope["record"]).get("contract") or "")
    _store(run, work)
    await scheduler.advance(db, run)
