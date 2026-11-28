"""The scheduler's one entry for every intake sync task."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, User, WorkItemSyncConfig
from .registry import entry_for_task_type, source_for


class IntakeTaskError(ValueError):
    pass


async def _config_of(db: AsyncSession, task: Task) -> WorkItemSyncConfig | None:
    config_id = str((task.config or {}).get("sync_config_id") or "").strip()
    return await db.get(WorkItemSyncConfig, config_id) if config_id else None


async def source_of_task(db: AsyncSession, task: Task) -> Any:
    entry = entry_for_task_type(task.task_type)
    if entry is not None:
        return source_for(entry.source_type)
    row = await _config_of(db, task)
    source = source_for(row.source_type) if row is not None else None
    if source is None:
        raise IntakeTaskError("intake sync task without its intake or a known source")
    return source


async def analyze_after_sync(db: AsyncSession, *, row: WorkItemSyncConfig, owner: User) -> dict[str, Any]:
    from ...work_item_analysis.auto_start import auto_analyze_after_sync  # opt-in per Workspace

    return await auto_analyze_after_sync(db, project_id=row.project_id, source_type=row.source_type, actor=owner)


async def run_scheduled_intake(db: AsyncSession, *, task: Task, task_run: Any) -> dict[str, Any]:
    source = await source_of_task(db, task)
    output = await source.run_scheduled(db, task=task, task_run=task_run)
    if source.analyzes_after_sync:
        return output
    row = await _config_of(db, task)
    owner = await db.get(User, task.owner_id)
    if row is not None and owner is not None:
        output["auto_analyze"] = await analyze_after_sync(db, row=row, owner=owner)
    if task_run is not None:
        task_run.output = output
    return output


__all__ = ["IntakeTaskError", "analyze_after_sync", "run_scheduled_intake", "source_of_task"]
