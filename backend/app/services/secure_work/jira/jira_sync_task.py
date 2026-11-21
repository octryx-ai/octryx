"""The scheduled Jira sync task: runs the configured sync and starts opted-in automatic analyses."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    Task,
    User,
    WorkItemSyncConfig,
)
from ..jira_values import optional_int
from .jira_sync import run_jira_work_item_sync
from .jira_sync_schedule import WORK_JIRA_SYNC_TASK_TYPE


async def run_scheduled_jira_work_item_sync(
    db: AsyncSession,
    *,
    task: Task,
    task_run,
) -> dict[str, Any]:
    config = dict(task.config or {})
    config_id = str(config.get("sync_config_id") or "").strip()
    if not config_id:
        raise ValueError("sync_config_id is required for secure_work_jira_sync tasks")
    owner = await db.get(User, task.owner_id)
    if owner is None:
        raise ValueError("Task owner not found")
    payload: dict[str, Any] = {"trigger": "scheduler"}
    limit = optional_int(config.get("limit"))
    if limit is not None:
        payload["limit"] = limit
    result = await run_jira_work_item_sync(
        db,
        config_id=config_id,
        current_user=owner,
        payload=payload,
        dry_run=False,
    )
    summary = result["sync_run"].get("summary") or {}
    task_run.output = {
        "mode": WORK_JIRA_SYNC_TASK_TYPE,
        "sync_config_id": config_id,
        "sync_run_id": result["sync_run"]["id"],
        "summary": summary,
    }
    from ...work_item_analysis.auto_start import auto_analyze_after_sync  # opt-in per Workspace

    sync_config = await db.get(WorkItemSyncConfig, config_id)
    task_run.output["auto_analyze"] = await auto_analyze_after_sync(
        db, project_id=sync_config.project_id if sync_config else None, source_type="jira", actor=owner)
    return task_run.output
