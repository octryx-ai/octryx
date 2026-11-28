"""Loop guard: a looping run is paused with its device jobs stopped, announced as paused, and its requester's queue
(the phone push) says so."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import DeviceJob, Project, Session, UserDevice, WorkflowRun, WorkflowRunEvent, WorkflowRunSession
from app.services.attention.service import attention
from app.services.mobile.push import group_of
from app.services.problems import alerts
from app.time_utils import utc_now


def uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_a_looping_run_is_paused_its_jobs_stopped_and_its_requester_is_told(db, auth_user):
    now = utc_now()
    project = Project(id=uid(), name="Kitchen helper", is_active=True, config={})
    device = UserDevice(owner_user_id=auth_user.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    db.add_all([project, device])
    await db.flush()
    await alerts.sweep(db, now=now)
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                      title="Team delivery", status="running", current_node_id="work", requested_by=auth_user.id,
                      updated_at=now)
    calm = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                       title="Calm run", status="running", current_node_id="work", requested_by=auth_user.id,
                       updated_at=now)
    db.add_all([run, calm])
    await db.flush()
    item = Session(id=uid(), user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", status="active",
                   metadata_={})
    db.add(item)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=item.id, role="child"))
    job = DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=item.id, workspace_id=project.id,
                    folder="/kitchen-helper/.octryx-items/frontend-shell", profile="seat", status="running", turn_state="accepted")
    db.add(job)
    for n in range(12):
        db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=now - timedelta(seconds=3 * n),
                                detail={"item": "core-domain", "status": "running", "iteration": 1}))
    await db.flush()

    result = await alerts.sweep(db, now=now)

    await db.refresh(run)
    await db.refresh(calm)
    await db.refresh(job)
    assert result["paused_loops"] == 1
    assert (run.status, run.pause_reason, calm.status) == ("paused", "loop_detected", "running")
    pause = run.node_state["pause"]
    assert (pause["item"], pause["count"]) == ("core-domain", 12) and pause["message"].startswith("Loop detected")
    assert pause["resume"] == {"kind": "restart", "node_id": "work"}
    assert job.stop_state == "pending"
    assert f"run:{run.id}:paused" in await alerts.open_alerts(db)
    queue = await attention(db, auth_user)
    [entry] = [item for item in queue["items"] if item.get("id") == run.id and item["kind"] == "problem"]
    assert group_of(entry) == "problem" and entry["text"].startswith("Loop detected")
    assert entry["title"].startswith("Loop detected, Team delivery paused: core-domain dispatched 12×")
    assert (await alerts.sweep(db, now=now))["paused_loops"] == 0


@pytest.mark.asyncio
async def test_refused_jobs_and_waiting_items_alone_never_pause_a_run(db, auth_user):
    now = utc_now()
    project = Project(id=uid(), name="Busy", is_active=True, config={})
    device = UserDevice(owner_user_id=auth_user.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k")
    db.add_all([project, device])
    await db.flush()
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                      title="Six items", status="running", current_node_id="work", requested_by=auth_user.id,
                      updated_at=now)
    db.add(run)
    await db.flush()
    for n in range(6):
        item = f"item-{n}"
        for k in range(8):
            db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=now - timedelta(seconds=k),
                                    detail={"item": item, "status": "pending", "iteration": 1,
                                            "reason": "device_busy"}))
        for iteration in (1, 2, 3, 4):
            db.add(WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=now - timedelta(seconds=iteration),
                                    detail={"item": item, "status": "running", "iteration": iteration}))
        session = Session(id=uid(), user_id=auth_user.id, project_id=project.id, agent_type="diagnosis",
                          status="active", metadata_={})
        db.add(session)
        await db.flush()
        db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="child"))
        db.add(DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=session.id, workspace_id=project.id,
                         folder="/w", profile="seat", status="rejected", status_reason="workspace_dirty",
                         created_at=now, updated_at=now))
    await db.flush()

    result = await alerts.sweep(db, now=now)

    await db.refresh(run)
    assert result["paused_loops"] == 0 and run.status == "running"
