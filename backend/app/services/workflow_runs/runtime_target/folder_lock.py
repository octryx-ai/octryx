"""One run per device folder (``folder_busy``)."""

from __future__ import annotations

import posixpath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import WorkflowRunError
from ..states import ACTIVE_STATUSES, STATUS_WAITING, WAITING_WATCH
from .target import KIND_DEVICE, stored_target

MAX_DEPTH = 20


def folder_key(target: dict[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(target, dict) or target.get("kind") != KIND_DEVICE:
        return None
    device, folder = str(target.get("device_id") or ""), str(target.get("folder") or "").strip()
    return (device, posixpath.normpath(folder).rstrip("/")) if device and folder else None


async def _root(db: AsyncSession, run_id: str | None) -> str | None:
    current, seen = run_id, 0
    while current and seen < MAX_DEPTH:
        run = await db.get(WorkflowRun, current)
        if run is None or not run.parent_run_id:
            return current
        current, seen = run.parent_run_id, seen + 1
    return current


def holds_folder(run: WorkflowRun) -> bool:
    return run.status in ACTIVE_STATUSES and not (run.status == STATUS_WAITING and run.waiting_kind == WAITING_WATCH)


async def folder_holder(db: AsyncSession, target: dict[str, Any] | None, *, run_id: str | None = None,
                        parent_run_id: str | None = None) -> WorkflowRun | None:
    key = folder_key(target)
    if key is None:
        return None
    own_root = await _root(db, run_id or parent_run_id)
    rows = (await db.execute(select(WorkflowRun).where(WorkflowRun.status.in_(tuple(ACTIVE_STATUSES))))).scalars()
    for other in rows:
        if other.id == run_id or not holds_folder(other) or folder_key(stored_target(other)) != key:
            continue
        if own_root is not None and await _root(db, other.id) == own_root:
            continue
        return other
    return None


async def refuse_busy_folder(db: AsyncSession, target: dict[str, Any] | None, *, run_id: str | None = None,
                             parent_run_id: str | None = None) -> None:
    other = await folder_holder(db, target, run_id=run_id, parent_run_id=parent_run_id)
    if other is not None:
        key = folder_key(target)
        raise WorkflowRunError(
            "folder_busy", f"The device folder {key[1]} is in use by run {other.id[:8]} ({other.workflow_key}, "
            f"{other.status}): one folder is one working tree. Choose another folder (a separate clone) or wait "
            "until that run ends.", 409)


__all__ = ["folder_holder", "folder_key", "holds_folder", "refuse_busy_folder"]
