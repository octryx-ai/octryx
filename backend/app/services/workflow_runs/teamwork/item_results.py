"""An item's reports to the scheduler: its result, a refused start, its turn's end and its merge."""

from __future__ import annotations

from typing import Any

from . import BLOCKED, CONFLICT, DONE, FAILED, MERGED, PENDING, RESULT_BLOCKED, RESULT_DONE, RUNNING, scheduler, work_of
from .item_order import _now, count_refusal, executor_of
from .scheduler import _at_node, _event, _store

MAX_ATTEMPTS = 2  # the first start and one retry after a transient failure
REASON_TRANSIENT = "transient_retry"


def _item(run: Any, key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    work = work_of(run)
    item = dict(work.get("items") or {}).get(key)
    return work, dict(item) if isinstance(item, dict) else None


def _put(run: Any, work: dict[str, Any], item: dict[str, Any]) -> None:
    work["items"] = {**dict(work.get("items") or {}), item["id"]: item}
    _store(run, work)


def record_result(run: Any, key: str, record: dict[str, Any]) -> bool:
    """The item's ``submit_phase_result`` (done / blocked) while it runs; ``False`` when it is not running."""
    work, item = _item(run, key)
    if item is None or item.get("status") != RUNNING:
        return False
    item["result"] = {"value": record.get("value"), "summary": record.get("summary") or ""}
    _put(run, work, item)
    return True


async def item_start_refused(db: Any, run: Any, *, key: str, session_id: str, reason: str) -> None:
    """The device turned the item's job down before its agent ran (``job_rejected``: registration, the folder's
    preparation): counted by :func:`count_refusal`, then the scheduler goes on (otherwise
    ``workspace_preparation_workflow_run_not_bound`` and ``environment_not_ready`` each started a new session)."""
    from ....models import Session
    from . import session_works_on

    work, item = _item(run, key)
    if item is None or not _at_node(run, work) or item.get("status") != RUNNING:
        return
    if not session_works_on(run, item, await db.get(Session, session_id) if session_id else None):
        return
    count_refusal(item, reason)
    _put(run, work, item)
    _event(db, run, item, session_id=session_id, refused=True)
    await scheduler.advance(db, run)


def note_start_problem(run: Any, key: str, detail: str) -> None:
    """Why the device could not prepare the item's folder (its preparation report), shown with the refusal."""
    work, item = _item(run, key)
    if item is not None and _at_node(run, work):
        item["start_detail"] = str(detail or "")[:600] or None
        _put(run, work, item)


async def item_finished(db: Any, run: Any, *, key: str, session_id: str, state: str, transient: bool = False,
                        reason: str | None = None) -> None:
    """An item's turn ended (see ``teamwork/__init__`` point 2)."""
    from ....models import Session
    from . import session_works_on

    work, item = _item(run, key)
    if item is None or not _at_node(run, work) or item.get("status") != RUNNING:
        return  # the node moved on or the item already ended: nothing changes
    if not session_works_on(run, item, await db.get(Session, session_id) if session_id else None):
        return  # an older session of the item (a device item's gateway session counts as its own)
    value = dict(item.get("result") or {}).get("value")
    if transient and int(item.get("attempts") or 0) < MAX_ATTEMPTS:
        item.update(status=PENDING, reason=REASON_TRANSIENT)
    elif transient:
        item.update(status=FAILED, reason=reason or "the model failed twice in a row")
    elif value == RESULT_BLOCKED:
        item.update(status=BLOCKED, reason=dict(item.get("result") or {}).get("summary") or "blocked")
    elif state == "passed" and value == RESULT_DONE:
        item.update(status=DONE, reason=None)
    else:
        item.update(status=FAILED, reason=reason or ("its checks did not pass" if state != "passed"
                                                     else "it ended without recording done or blocked"))
    item.update(finished_at=_now(), start_refusals=0, start_detail=None)  # its agent ran: refusals start over
    _put(run, work, item)
    _event(db, run, item, session_id=session_id)
    if item["status"] == DONE:
        executor = await executor_of(db, run, work)
        await executor.merge(db, run, item)  # the server merges at once and reports; the device queues it
        return
    await scheduler.advance(db, run)


async def merge_reported(db: Any, run: Any, *, key: str, merged: bool, conflicts: list[str] | None = None,
                         merged_sha: str | None = None) -> None:
    """The item's merge into the story's working copy happened: ``merged``, or ``conflict`` with its files."""
    work, item = _item(run, key)
    if item is None or not _at_node(run, work) or item.get("status") != DONE:
        return
    if merged:
        item.update(status=MERGED, merged_sha=merged_sha, merged_at=_now(), conflicts=None, reason=None)
    else:
        item.update(status=CONFLICT, conflicts=list(conflicts or []) or ["merge_failed"], reason="merge_conflict")
    _put(run, work, item)
    _event(db, run, item, merged=merged, **({"conflicts": item["conflicts"]} if not merged else {}))
    await scheduler.advance(db, run)
