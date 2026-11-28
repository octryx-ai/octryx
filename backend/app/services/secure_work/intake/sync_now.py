"""Sync now: run an enabled intake's sync on request."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, User, WorkItemSyncConfig
from .runs import TRIGGER_MANUAL
from .setup import first_run

SYNC_NOW_AUDIT_ACTION = "secure_work.intake.sync_now"
CODE_NOT_ENABLED = "intake_not_enabled"
STATE_RAN = "ran"


async def sync_now(db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]:
    # Enabled only after a preview of its current settings: a sync now must not bypass that
    if not row.is_active:
        raise HTTPException(status_code=409, detail={"state": "needs_configuration", "code": CODE_NOT_ENABLED,
                                                     "message": "Enable the intake before syncing it."})
    result = await first_run(db, user=user, row=row)
    run = dict(result.get("sync_run") or {})
    status = str(run.get("status") or "")
    state = STATE_RAN if status == "completed" else status or "failed"
    db.add(AuditLog(user_id=user.id, action=SYNC_NOW_AUDIT_ACTION, resource_type="work_item_sync_config",
                    project_id=row.project_id,
                    resource_id=row.id, details={"project_id": row.project_id, "source_type": row.source_type,
                                                 "sync_run_id": run.get("id"), "state": state}))
    await db.flush()
    return {"state": state, "intake_id": row.id, "source_type": row.source_type, "trigger": TRIGGER_MANUAL,
            "sync_run": run, "summary": dict(result.get("summary") or run.get("summary") or {})}


__all__ = ["CODE_NOT_ENABLED", "SYNC_NOW_AUDIT_ACTION", "sync_now"]
