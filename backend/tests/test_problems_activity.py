"""Activity problems: looping and silent runs, refused and stalled device jobs (live monitoring, P1).

The looping case replays Kitchen helper rehearsal R1: one item dispatched over and over at
iteration 1, each dispatch a new session whose device job the Mac refused.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    DeviceJob,
    DeviceJobEvent,
    Project,
    Session,
    User,
    UserDevice,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
)
from app.services.problems import activity
from app.services.problems.model import CollectContext
from app.services.problems.service import COLLECTORS
from app.time_utils import utc_now

NOW = utc_now()


def uid() -> str:
    return str(uuid.uuid4())


async def _setup(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name=f"Activity {uid()[:6]}", is_active=True, config={})
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos",
                        public_key="k", last_seen_at=NOW)
    db.add_all([project, device])
    await db.flush()
    return project, admin, device, CollectContext(now=NOW, workspace_ids=frozenset({project.id}))


def _run(project, admin, *, status="running", age=timedelta(minutes=1), **extra) -> WorkflowRun:
    return WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                       title="Team delivery", status=status, requested_by=admin.id, updated_at=NOW - age, **extra)


async def _session(db, admin, run, role="child") -> Session:
    session = Session(id=uid(), user_id=admin.id, agent_type="diagnosis", status="active", metadata_={})
    db.add(session)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role=role))
    return session


def _item_event(run, item: str, status: str, seconds_ago: int, iteration: int = 1) -> WorkflowRunEvent:
    return WorkflowRunEvent(run_id=run.id, kind="work_item", created_at=NOW - timedelta(seconds=seconds_ago),
                            detail={"item": item, "status": status, "iteration": iteration, "executor": "device"})


def _of(problems, run_id, code):
    return [item for item in problems if item.object_id == run_id and item.reason_code == code]


@pytest.mark.asyncio
async def test_rehearsal_r1_loop_is_a_looping_run_with_refused_jobs(db):
    project, admin, device, ctx = await _setup(db)
    loop = _run(project, admin)
    healthy = _run(project, admin)
    db.add_all([loop, healthy])
    await db.flush()
    await _session(db, admin, loop, role="main")
    # R1: core-domain re-dispatched at iteration 1, every 2 s; each dispatch a session and a refused device job.
    for n in range(12):
        db.add(_item_event(loop, "core-domain", "running", seconds_ago=2 * n))
        item_session = await _session(db, admin, loop)
        db.add(DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=item_session.id,
                         workspace_id=project.id, folder="/kitchen-helper/.octryx-items/core-domain", profile="seat",
                         status="rejected", status_reason="workspace_preparation_workflow_run_not_bound",
                         created_at=NOW - timedelta(seconds=2 * n), updated_at=NOW - timedelta(seconds=2 * n)))
    # A healthy run: three items each moving pending -> running -> done, and a second iteration of one of them.
    for item in ("a", "b", "c"):
        for status in ("pending", "running", "done"):
            db.add(_item_event(healthy, item, status, seconds_ago=30))
    for status in ("pending", "running", "done"):
        db.add(_item_event(healthy, "a", status, seconds_ago=10, iteration=2))
    await db.flush()

    problems = await activity.collect(db, ctx)

    looping = _of(problems, loop.id, "looping")
    assert [(item.severity, item.count) for item in looping] == [("problem", 12)]
    assert "core-domain" in looping[0].title
    assert looping[0].fix["href"].startswith("/chat?session_id=")
    refused = _of(problems, loop.id, "jobs_rejected")
    assert refused[0].count == 12
    assert "workspace preparation workflow run not bound" in refused[0].title
    assert not [item for item in problems if item.object_id == healthy.id]


@pytest.mark.asyncio
async def test_a_stopped_run_and_old_dispatches_are_not_a_loop(db):
    project, admin, _device, ctx = await _setup(db)
    stopped = _run(project, admin, status="stopped")
    old = _run(project, admin)
    db.add_all([stopped, old])
    await db.flush()
    for n in range(12):
        db.add(_item_event(stopped, "core-domain", "running", seconds_ago=n))
        db.add(_item_event(old, "core-domain", "running", seconds_ago=int(activity.LOOP_WINDOW.total_seconds()) + 60))
    await db.flush()

    problems = await activity.collect(db, ctx)

    assert not [item for item in problems if item.reason_code == "looping"]


@pytest.mark.asyncio
async def test_silent_runs_by_their_last_event_or_job_and_waiting_for_a_person_is_not_silent(db):
    project, admin, device, ctx = await _setup(db)
    quiet = _run(project, admin, age=timedelta(hours=2))
    very_quiet = _run(project, admin, age=timedelta(hours=2))
    device_wait = _run(project, admin, status="waiting", waiting_kind="waiting_for_device", age=timedelta(hours=2))
    busy_on_device = _run(project, admin, age=timedelta(hours=2))
    person_wait = _run(project, admin, status="waiting", waiting_kind="waiting_for_reply", age=timedelta(hours=2))
    db.add_all([quiet, very_quiet, device_wait, busy_on_device, person_wait])
    await db.flush()
    db.add(WorkflowRunEvent(run_id=quiet.id, kind="node_entered", detail={}, created_at=NOW - timedelta(minutes=25)))
    db.add(WorkflowRunEvent(run_id=very_quiet.id, kind="node_entered", detail={},
                            created_at=NOW - timedelta(minutes=50)))
    # The run itself is quiet but its item job on the Mac changed a minute ago: it works.
    session = await _session(db, admin, busy_on_device)
    db.add(DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=session.id, workspace_id=project.id,
                     folder="/w", profile="seat", status="running", updated_at=NOW - timedelta(minutes=1)))
    await db.flush()

    problems = await activity.collect(db, ctx)

    assert [item.severity for item in _of(problems, quiet.id, "silent")] == ["attention"]
    assert "25 minutes" in _of(problems, quiet.id, "silent")[0].title
    assert [item.severity for item in _of(problems, very_quiet.id, "silent")] == ["problem"]
    assert [item.severity for item in _of(problems, device_wait.id, "silent")] == ["problem"]
    assert not _of(problems, busy_on_device.id, "silent")
    assert not _of(problems, person_wait.id, "silent")


@pytest.mark.asyncio
async def test_a_running_device_job_without_events_is_stalled(db):
    project, admin, device, ctx = await _setup(db)
    chat = Session(id=uid(), user_id=admin.id, agent_type="diagnosis", status="active", metadata_={})
    db.add(chat)
    await db.flush()

    def job(minutes: int, **extra) -> DeviceJob:
        return DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=chat.id, workspace_id=project.id,
                         folder="/kitchen-helper/.octryx-items/fix-effort", profile="seat", status="running",
                         updated_at=NOW - timedelta(minutes=minutes), **extra)

    stalled, talking, away = job(40), job(40), job(40, disconnected_at=NOW - timedelta(minutes=2))
    db.add_all([stalled, talking, away])
    await db.flush()
    db.add(DeviceJobEvent(job_id=talking.id, seq=1, type="text", body={}, created_at=NOW - timedelta(minutes=2)))
    await db.flush()

    problems = await activity.collect(db, ctx)

    found = [item for item in problems if item.reason_code == "job_stalled"]
    assert [item.object_id for item in found] == [stalled.id]
    assert found[0].object_name == "fix-effort" and found[0].key == f"device:{stalled.id}:job_stalled"


def test_the_problems_list_runs_the_activity_collector():
    assert activity.collect in COLLECTORS
