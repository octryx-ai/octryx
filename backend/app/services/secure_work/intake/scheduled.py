"""The scheduler's one entry for every intake sync task.

A task names its intake (``config.sync_config_id``). Its source is the registry entry whose own task type it carries
(``secure_work_jira_sync``, ``secure_work_servicenow_sync``: stored tasks keep working), or, for the generic
``secure_work_work_intake_sync``, the intake's ``source_type``. The same task also runs when an inbound webhook
triggers the intake (``inbound_alerts/trigger``): it is a sync, never an agent turn.

Every scheduled sync then starts the Workspace's automatic analyses (opt-in, ``work_item_analysis/auto_start``).
All scheduled runners trigger enabled analyses (ServiceNow schedules must analyse new incidents too,
when ``auto_analyze.servicenow_new_incidents`` is enabled). A source whose runner already analyses (Jira)
says so (``analyzes_after_sync``) and is not analysed twice.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, User, WorkItemSyncConfig
from .registry import entry_for_task_type, source_for


class IntakeTaskError(ValueError):
    """A sync task without its intake, owner or a known source."""


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
    """Run the task's intake sync; ``task_run.output`` is the run and its summary (and the analyses started)."""
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
