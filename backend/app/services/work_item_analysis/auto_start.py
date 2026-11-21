"""Automatic analyses after an intake sync, opt-in per Workspace, default off.

``auto_analyze_after_sync(db, project_id=..., source_type=..., actor=...)`` runs after a sync of one
Workspace's intake (the Jira scheduled sync calls it; the ServiceNow intake calls it the same way):

- ``servicenow``: only with ``auto_analyze.servicenow_new_incidents``; items from the ``incident`` table in
  the ``intake`` state (New).
- ``jira``: only with ``auto_analyze.jira_label``; items carrying that label (case-insensitive).
- every other registered Work source (``secure_work/intake/registry``) decides by its own
  ``wants_auto_analysis`` (e.g. a Custom REST intake's ``auto_analyze_new`` option); an unknown source never.
- Never a closed item, at most one automatic analysis per item in 24 hours (``runner``), and at most
  :data:`MAX_PER_SYNC` analyses per sync, newest items first.
- Never with ``runner: seat``: the server does not start seat analyses; a user runs them in a seat session.

Each analysis runs as ``mode: auto`` on behalf of ``actor`` (the sync's owner). The sync's own writes are
committed before the first analysis starts; a failure is logged and reported in the summary and never fails
or undoes the sync.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User, WorkItem, WorkItemSyncConfig
from .runner import CLOSED_STATES, MODE_AUTO, analyze_work_item, recent_auto_run
from .settings import RUNNER_SEAT, AnalysisSettings, settings_from_config

logger = logging.getLogger(__name__)
MAX_PER_SYNC = 5


def _wanted(item: WorkItem, settings: AnalysisSettings, options: dict[str, dict]) -> bool:
    """The item's source decides (``wants_auto_analysis``); the intake's own options are passed for sources that
    switch it per intake."""
    from ..secure_work.intake.registry import source_for

    source = source_for(item.source_type)
    return bool(source is not None
                and source.wants_auto_analysis(item, settings, options.get(str(item.sync_config_id or ""), {})))


async def _intake_options(db: AsyncSession, project_id: str, source_type: str) -> dict[str, dict]:
    rows = (await db.execute(select(WorkItemSyncConfig.id, WorkItemSyncConfig.sync_options_json).where(
        WorkItemSyncConfig.project_id == project_id, WorkItemSyncConfig.source_type == source_type))).all()
    return {str(config_id): dict(options or {}) for config_id, options in rows}


async def auto_candidates(db: AsyncSession, *, project_id: str, source_type: str) -> list[WorkItem]:
    project = await db.get(Project, project_id)
    settings, _source = settings_from_config(project.config if project is not None else None)
    if settings.runner == RUNNER_SEAT:
        return []
    options = await _intake_options(db, project_id, source_type)
    rows = (await db.execute(
        select(WorkItem).where(WorkItem.project_id == project_id, WorkItem.source_type == source_type,
                               WorkItem.work_state.not_in(sorted(CLOSED_STATES)))
        .order_by(WorkItem.imported_at.desc()).limit(200)
    )).scalars().all()
    return [item for item in rows if _wanted(item, settings, options)]


async def auto_analyze_after_sync(
    db: AsyncSession, *, project_id: str | None, source_type: str, actor: User, **run_options: Any
) -> dict[str, Any]:
    """Start the eligible automatic analyses; returns ``{started, results}``. Never raises."""
    if not project_id:
        return {"started": 0, "results": []}
    try:
        candidates = await auto_candidates(db, project_id=project_id, source_type=source_type)
        if candidates:
            await db.commit()  # the sync's result is kept whatever an analysis does (each analysis commits)
        results = []
        for item in candidates:
            if len(results) >= MAX_PER_SYNC:
                break
            if await recent_auto_run(db, item.id):
                continue
            answer = await analyze_work_item(db, item=item, user=actor, mode=MODE_AUTO, **run_options)
            results.append({"work_item_id": item.id, "status": answer["status"],
                            "error_code": answer.get("error_code")})
    except Exception:  # noqa: BLE001 - the sync it follows has already succeeded
        logger.exception("work_item_auto_analysis_failed project_id=%s source=%s", project_id, source_type)
        await db.rollback()
        return {"started": 0, "results": [], "error": "auto_analyze_failed"}
    return {"started": len(results), "results": results}


__all__ = ["MAX_PER_SYNC", "auto_analyze_after_sync", "auto_candidates"]
