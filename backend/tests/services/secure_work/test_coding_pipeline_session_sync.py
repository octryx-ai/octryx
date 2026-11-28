"""A dead coding-agent session fails its pipeline run: the cockpit never shows 'running' for an agent that stopped
(loop guard, validation failure, user stop)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import User, WorkCodingPipelineRun, WorkCodingPipelineStage, WorkItem
from app.services.secure_work.coding.coding_pipeline_session_sync import fail_pipeline_runs_for_session
from app.time_utils import utc_now


async def _seed_running_pipeline(db, *, session_id: str) -> WorkCodingPipelineRun:
    token = uuid.uuid4().hex[:8]
    item = WorkItem(
        source_type="jira",
        source_instance="test",
        source_key=f"SYNC-{token}",
        title="Sync test item",
        work_state="in_progress",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    run = WorkCodingPipelineRun(
        work_item_id=item.id,
        status="running",
        control_state="running",
        current_stage_key="context_collection",
        summary_json={},
        recovery_state_json={"agent_session_id": session_id},
        started_by=admin.id,
        updated_by=admin.id,
        started_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(run)
    await db.flush()
    db.add(
        WorkCodingPipelineStage(
            run_id=run.id,
            stage_key="context_collection",
            label="Context Collection",
            stage_order=1,
            status="running",
        )
    )
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_stopped_session_fails_running_pipeline(db):
    session_id = str(uuid.uuid4())
    run = await _seed_running_pipeline(db, session_id=session_id)

    transitioned = await fail_pipeline_runs_for_session(
        db, session_id=session_id, run_status="stopped", reason="agent_stopped"
    )
    assert transitioned == 1

    await db.refresh(run)
    assert run.status == "failed" and run.control_state == "failed"
    assert "agent_session_stopped" in (run.error or "")
    assert run.summary_json["agent_session_terminal"]["reason"] == "agent_stopped"

    stage = (
        await db.execute(
            select(WorkCodingPipelineStage).where(WorkCodingPipelineStage.run_id == run.id)
        )
    ).scalar_one()
    assert stage.status == "failed"
    assert "agent session terminal" in stage.outputs_json["failure_reason"]


@pytest.mark.asyncio
async def test_completed_session_does_not_touch_pipeline(db):
    session_id = str(uuid.uuid4())
    run = await _seed_running_pipeline(db, session_id=session_id)

    transitioned = await fail_pipeline_runs_for_session(
        db, session_id=session_id, run_status="completed", reason="completed"
    )
    assert transitioned == 0
    await db.refresh(run)
    assert run.status == "running"


@pytest.mark.asyncio
async def test_other_sessions_pipelines_untouched(db):
    run = await _seed_running_pipeline(db, session_id=str(uuid.uuid4()))

    transitioned = await fail_pipeline_runs_for_session(
        db, session_id=str(uuid.uuid4()), run_status="stopped", reason="agent_stopped"
    )
    assert transitioned == 0
    await db.refresh(run)
    assert run.status == "running"
