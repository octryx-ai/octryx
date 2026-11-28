"""Keep coding pipeline runs in sync with their agent session's run state. A terminal failure of the session fails the
run explicitly; a successful turn is not propagated."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkCodingPipelineRun
from ....time_utils import utc_now

logger = logging.getLogger(__name__)

_TERMINAL_FAILURE_STATUSES = {"stopped", "failed"}


async def fail_pipeline_runs_for_session(
    db: AsyncSession,
    *,
    session_id: str,
    run_status: str,
    reason: str | None,
) -> int:
    normalized_status = str(run_status or "").strip().lower()
    if normalized_status not in _TERMINAL_FAILURE_STATUSES or not session_id:
        return 0
    runs = (
        (
            await db.execute(
                select(WorkCodingPipelineRun).where(WorkCodingPipelineRun.status == "running")
            )
        )
        .scalars()
        .all()
    )
    transitioned = 0
    now = utc_now()
    for run in runs:
        recovery = dict(run.recovery_state_json or {})
        if str(recovery.get("agent_session_id") or "") != session_id:
            continue
        detail = str(reason or "").strip() or normalized_status
        run.status = "failed"
        run.control_state = "failed"
        run.error = f"agent_session_{normalized_status}: {detail}"
        run.updated_at = now
        run.summary_json = {
            **dict(run.summary_json or {}),
            "agent_session_terminal": {
                "session_id": session_id,
                "run_status": normalized_status,
                "reason": detail,
                "observed_at": now.isoformat(),
            },
        }
        await _fail_current_stage(db, run, detail=detail, now=now)
        transitioned += 1
        logger.warning(
            "coding_pipeline.failed_by_session run=%s session=%s reason=%s",
            run.id,
            session_id,
            detail,
        )
    if transitioned:
        await db.flush()
    return transitioned


async def _fail_current_stage(
    db: AsyncSession, run: WorkCodingPipelineRun, *, detail: str, now: Any
) -> None:
    from ....models import WorkCodingPipelineStage

    stage = (
        await db.execute(
            select(WorkCodingPipelineStage).where(
                WorkCodingPipelineStage.run_id == run.id,
                WorkCodingPipelineStage.stage_key == run.current_stage_key,
            )
        )
    ).scalar_one_or_none()
    if stage is None or stage.status in {"completed", "failed", "skipped"}:
        return
    stage.status = "failed"
    stage.completed_at = now
    stage.outputs_json = {
        **dict(stage.outputs_json or {}),
        "failure_reason": f"agent session terminal: {detail}",
    }


__all__ = ["fail_pipeline_runs_for_session"]
