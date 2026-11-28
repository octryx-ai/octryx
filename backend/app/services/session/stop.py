"""Helpers for explicit user-triggered chat session stop flows."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, TaskRun
from ...time_utils import utc_now
from .run_state import RUN_STATUS_STOPPED, set_session_run_state
from .workspace import get_session_workspace_root
from .workspace_sync import sync_workspace_full

logger = logging.getLogger(__name__)

_TERMINAL_TASK_RUN_STATUSES = {
    "success",
    "completed",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "stopped",
    "skipped",
}


async def finalize_user_stopped_session(
    db: AsyncSession,
    *,
    session: Session,
) -> None:
    if str(session.status or "").strip().lower() == "running":
        session.status = "active"

    metadata = dict(session.metadata_ or {})
    metadata["last_stop_reason"] = "user_cancelled"
    metadata.pop("current_turn_started_at", None)
    metadata.pop("run_started_at", None)
    session.metadata_ = metadata
    set_session_run_state(session, RUN_STATUS_STOPPED, "user_cancelled")
    try:
        # A user-stopped coding agent must not leave its pipeline run "running".
        from ..secure_work.coding.coding_pipeline_session_sync import fail_pipeline_runs_for_session

        await fail_pipeline_runs_for_session(
            db, session_id=session.id, run_status=RUN_STATUS_STOPPED, reason="user_cancelled"
        )
    except Exception:  # noqa: BLE001 - pipeline sync must not break the stop flow
        logger.exception("coding_pipeline_session_sync_failed", extra={"session_id": session.id})
    try:
        workspace_root = await get_session_workspace_root(db, session.id, create=False)
        sync_result = await sync_workspace_full(
            db=db,
            session_id=session.id,
            workspace_root=workspace_root,
            reason="user_stopped",
        )
        if sync_result.get("status") == "error":
            logger.warning("Session workspace stop sync failed", extra={"session_id": session.id, "sync": sync_result})
    except Exception:
        logger.exception("Failed to run session workspace stop sync", extra={"session_id": session.id})

    linked_task_run = await _load_linked_task_run(db, session=session, metadata=metadata)
    if linked_task_run is None:
        return

    normalized_status = str(linked_task_run.status or "").strip().lower()
    if normalized_status in _TERMINAL_TASK_RUN_STATUSES:
        return

    linked_task_run.status = "cancelled"
    linked_task_run.completed_at = linked_task_run.completed_at or utc_now()


async def _load_linked_task_run(
    db: AsyncSession,
    *,
    session: Session,
    metadata: dict,
) -> TaskRun | None:
    task_run_id = str(metadata.get("task_run_id") or "").strip()
    if task_run_id:
        task_run = await db.get(TaskRun, task_run_id)
        if task_run is not None:
            return task_run

    return (
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.session_id == session.id)
                .order_by(TaskRun.started_at.desc(), TaskRun.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


__all__ = ["finalize_user_stopped_session"]
