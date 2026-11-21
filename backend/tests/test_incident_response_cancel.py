"""Cancelling running task and agent chain runs directly and when safe mode activates, and auto-resume of paused entities when safe mode is deactivated."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent.agent_chain import AgentChainRun
from app.models.project.task import TaskRun
from app.models.runtime.incident_response import TARGET_AGENT_CHAIN, TARGET_FLOW, TARGET_TASK
from app.services.incident_response.entities import cancel_running_runs, pause_entity
from app.services.incident_response.safe_mode import activate_safe_mode, deactivate_safe_mode
from tests.incident_response_support import _make_agent_chain, _make_flow, _make_project, _make_task, _uid


async def _make_task_run(
    db: AsyncSession, *, task_id: str, started_by: str | None = None, status: str = "in_progress"
) -> TaskRun:
    r = TaskRun(id=_uid(), task_id=task_id, status=status, started_by=started_by or _uid())
    db.add(r)
    await db.commit()
    return r


async def _make_agent_chain_run(
    db: AsyncSession, *, template_id: str, project_id: str, started_by: str | None = None, status: str = "in_progress"
) -> AgentChainRun:
    r = AgentChainRun(
        id=_uid(), template_id=template_id, project_id=project_id,
        status=status, started_by=started_by or _uid(),
    )
    db.add(r)
    await db.commit()
    return r


# ── Cancel Running Runs Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_running_runs_task(db: AsyncSession, auth_user):
    project = await _make_project(db)
    task = await _make_task(db, project_id=project.id)
    run1 = await _make_task_run(db, task_id=task.id, status="in_progress")
    run2 = await _make_task_run(db, task_id=task.id, status="in_progress")
    run3 = await _make_task_run(db, task_id=task.id, status="completed")

    result = await cancel_running_runs(
        db, target_type=TARGET_TASK, target_id=task.id,
        user_id=str(auth_user.id), reason="Emergency stop",
    )
    assert result["cancelled_runs"] == 2

    await db.refresh(run1)
    await db.refresh(run2)
    await db.refresh(run3)
    assert run1.status == "cancelled"
    assert run2.status == "cancelled"
    assert run3.status == "completed"  # unchanged


@pytest.mark.asyncio
async def test_cancel_running_runs_agent_chain(db: AsyncSession, auth_user):
    project = await _make_project(db)
    chain = await _make_agent_chain(db, project_id=project.id)
    run = await _make_agent_chain_run(db, template_id=chain.id, project_id=project.id)

    result = await cancel_running_runs(
        db, target_type=TARGET_AGENT_CHAIN, target_id=chain.id,
        user_id=str(auth_user.id),
    )
    assert result["cancelled_runs"] == 1

    await db.refresh(run)
    assert run.status == "cancelled"


# ── Safe Mode with cancel_running_work ───────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_safe_mode_cancels_running_work(db: AsyncSession, auth_user):
    project = await _make_project(db)
    task = await _make_task(db, project_id=project.id)
    run = await _make_task_run(db, task_id=task.id, status="in_progress")

    result = await activate_safe_mode(
        db,
        user_id=str(auth_user.id),
        reason="Emergency",
        project_id=project.id,
        cancel_running_work=True,
    )
    assert result["cancelled_runs"] >= 1

    await db.refresh(run)
    assert run.status == "cancelled"


# ── Auto-resume on deactivate ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivate_safe_mode_auto_resume(db: AsyncSession, auth_user):
    project = await _make_project(db)
    flow = await _make_flow(db, project_id=project.id)

    # Activate safe mode and pause the flow
    await activate_safe_mode(
        db, user_id=str(auth_user.id), reason="Test",
        project_id=project.id, incident_id="INC-TEST",
    )
    await pause_entity(
        db, target_type=TARGET_FLOW, target_id=flow.id,
        user_id=str(auth_user.id), incident_id="INC-TEST",
    )
    await db.refresh(flow)
    assert flow.is_active is False

    # Deactivate with auto_resume
    result = await deactivate_safe_mode(
        db, user_id=str(auth_user.id),
        project_id=project.id, auto_resume=True,
    )
    assert result["resumed_entities"] >= 1

    await db.refresh(flow)
    assert flow.is_active is True
