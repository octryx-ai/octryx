"""A status per task of a work item: only so can the platform guarantee one branch in development per
ticket or work item.

One work item is one branch; its tasks (the readiness check's task list, ``task_list.py``) are not work items of their
own but carry a status that the platform sets from what it can check, never from what the model says:

- ``open``: agreed, nothing in the change for it yet;
- ``in_progress``: its proof test is in the change, the building phase's gates are not green yet;
- ``done``: its proof test is in the change and the building phase passed every gate; in a workflow whose building
  phase is followed by the CI pipeline (``pipeline``): its proof test passed in the pipeline's run and the pipeline
  is green (:func:`after_pipeline`) — the pipeline, not the diff, proves a task;
- ``changes``: the independent review found the task not (or wrongly) carried out (a finding whose fix starts with
  ``T<n>:``); the finding is the task's note;
- ``verified``: the review passed with the task done.

The list is kept on the run (``context.task_list``) and on the work item (``work_items.task_list``), so a later run of
the same item starts from the statuses the last one reached: a task with the same id and proof keeps its status.
"""

from __future__ import annotations

import re
from typing import Any

from ...time_utils import utc_now
from .task_list import CONTEXT_KEY, missing_proofs

OPEN, IN_PROGRESS, DONE, CHANGES, VERIFIED = "open", "in_progress", "done", "changes", "verified"
STATUSES = (OPEN, IN_PROGRESS, DONE, CHANGES, VERIFIED)
_FINDING_TASK = re.compile(r"^\s*\**T(\d{1,2})\b")


def _now() -> str:
    return utc_now().isoformat()


def _stamp(item: dict[str, Any], status: str, run_id: str | None, note: str | None = None) -> dict[str, Any]:
    if item.get("status") == status and (note is None or item.get("note") == note):
        return item
    changed = {**item, "status": status, "run_id": run_id, "updated_at": _now()}
    if note is not None:
        changed["note"] = note
    elif status in (DONE, VERIFIED):
        changed.pop("note", None)
    return changed


def seed(items: list[dict[str, Any]], previous: list[dict[str, Any]] | None, run_id: str | None) -> list[dict[str,
                                                                                                              Any]]:
    """The new list with statuses: a task the item had already (same id and proof) keeps its status and note."""
    from .task_list import proofs_of

    known = {(str(item.get("id")), tuple(proofs_of(item))): item for item in previous or [] if isinstance(item, dict)}
    seeded = []
    for item in items:
        before = known.get((str(item.get("id")), tuple(proofs_of(item))))
        if before and before.get("status") in STATUSES:
            seeded.append({**item, **{key: before[key] for key in ("status", "note", "run_id", "updated_at")
                                      if key in before}})
        else:
            seeded.append({**item, "status": OPEN, "run_id": run_id, "updated_at": _now()})
    return seeded


def after_build(items: list[dict[str, Any]], change: Any, *, passed: bool, run_id: str | None,
                green: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Statuses after a building pass's Stop: proof test in the change → ``in_progress``, and ``done`` once the pass
    passed every gate; a task under review ``changes`` stays there until a passed pass carries its proof."""
    missing = missing_proofs(items, change, green)
    if missing is None:
        return items
    open_ids = {entry.split(" ", 1)[0] for entry in missing}
    updated = []
    for item in items:
        if item.get("id") in open_ids:
            updated.append(item if item.get("status") in (CHANGES, OPEN) else _stamp(item, OPEN, run_id))
        elif passed:
            updated.append(_stamp(item, DONE, run_id))
        elif item.get("status") == CHANGES:
            updated.append(item)
        else:
            updated.append(_stamp(item, IN_PROGRESS, run_id))
    return updated


def after_pipeline(items: list[dict[str, Any]], proven: set[str], *, green: bool,
                   run_id: str | None) -> list[dict[str, Any]]:
    """Statuses after the CI pipeline: a task whose proof passed there is ``done`` when the pipeline is green, else
    ``in_progress``; a task whose proof did not pass is ``open``. A task the review sent back (``changes``) leaves
    that state only as ``done``."""
    updated = []
    for item in items:
        if item.get("id") in proven and green:
            updated.append(_stamp(item, DONE, run_id))
        elif item.get("status") == CHANGES:
            updated.append(item)
        else:
            updated.append(_stamp(item, IN_PROGRESS if item.get("id") in proven else OPEN, run_id))
    return updated


def after_review(items: list[dict[str, Any]], verdict: str, findings: list[dict[str, Any]],
                 run_id: str | None) -> list[dict[str, Any]]:
    """A finding whose fix starts with ``T<n>`` sets that task to ``changes``; a passed review verifies done tasks."""
    notes: dict[str, str] = {}
    for finding in findings:
        match = _FINDING_TASK.match(str(finding.get("fix") or ""))
        if match and str(finding.get("severity") or "") in ("high", "medium"):
            notes.setdefault(f"T{int(match.group(1))}", str(finding.get("fix") or ""))
    updated = []
    for item in items:
        if item.get("id") in notes:
            updated.append(_stamp(item, CHANGES, run_id, notes[item["id"]]))
        elif verdict == "pass" and item.get("status") == DONE:
            updated.append(_stamp(item, VERIFIED, run_id))
        else:
            updated.append(item)
    return updated


async def store(db: Any, run: Any, items: list[dict[str, Any]]) -> None:
    """The list on the run and on its work item."""
    run.context = {**dict(run.context or {}), CONTEXT_KEY: items}
    if getattr(run, "work_item_id", None):
        from ...models.runtime.secure_work import WorkItem

        item = await db.get(WorkItem, run.work_item_id)
        if item is not None:
            item.task_list = items


async def previous(db: Any, run: Any) -> list[dict[str, Any]]:
    """The work item's list from its earlier runs."""
    if not getattr(run, "work_item_id", None):
        return []
    from ...models.runtime.secure_work import WorkItem

    item = await db.get(WorkItem, run.work_item_id)
    return [dict(entry) for entry in (getattr(item, "task_list", None) or []) if isinstance(entry, dict)]


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    tally = {status: 0 for status in STATUSES}
    for item in items:
        tally[str(item.get("status") or OPEN)] = tally.get(str(item.get("status") or OPEN), 0) + 1
    return tally


__all__ = ["CHANGES", "DONE", "IN_PROGRESS", "OPEN", "STATUSES", "VERIFIED", "after_build", "after_pipeline",
           "after_review", "counts",
           "previous", "seed", "store"]
