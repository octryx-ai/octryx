"""The run history of one intake and the trigger of a run (intake redesign §3.5).

A run's trigger (``manual`` or ``scheduled``) is recorded in its summary when it starts; a run recorded
before that reports none. The history lists the last :data:`MAX_RUNS` runs, newest first.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkItemSyncConfig, WorkItemSyncRun
from ..serializers import serialize_sync_run

MAX_RUNS = 20
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"


def trigger_of(payload: Mapping[str, Any] | None) -> str:
    """The trigger of a run request: the scheduler sends ``trigger: scheduler``; everything else is manual."""
    return TRIGGER_SCHEDULED if (payload or {}).get("trigger") == "scheduler" else TRIGGER_MANUAL


async def list_intake_runs(db: AsyncSession, row: WorkItemSyncConfig, limit: int = MAX_RUNS) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(WorkItemSyncRun)
            .where(WorkItemSyncRun.sync_config_id == row.id)
            .order_by(WorkItemSyncRun.created_at.desc())
            .limit(max(1, min(limit, MAX_RUNS)))
        )
    ).scalars()
    return [serialize_sync_run(run) for run in rows]


__all__ = ["MAX_RUNS", "TRIGGER_MANUAL", "TRIGGER_SCHEDULED", "list_intake_runs", "trigger_of"]
