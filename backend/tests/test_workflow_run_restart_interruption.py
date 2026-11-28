"""A running workflow run whose Server turn a restart interrupted pauses ``runtime_failed`` with a
``restart`` resume instead of hanging; unaffected runs are left as they are."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User, WorkflowRun, WorkflowRunEvent, WorkflowRunSession
from app.models import Session as ChatSession
from app.services.runtime_ownership.interrupted_turns import TRIGGER_STARTUP, settle_interrupted_turns
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state


async def _run_with_thread(
    db: AsyncSession, owner: User, *, run_status: str = "running", session_status: str = "running",
    device: bool = False,
) -> tuple[WorkflowRun, ChatSession]:
    project = Project(name=f"restart-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    metadata = {"execution_target": {"kind": "device", "device_id": "dev_x", "folder": "/w"}} if device else {}
    session = ChatSession(user_id=owner.id, project_id=project.id, status=session_status, metadata_=metadata)
    if session_status == "running":
        set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    session.turn_owner_process_id = str(uuid.uuid4())  # a process of the previous boot: no live lease
    run = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="feature-delivery-tdd",
                      requested_by=owner.id, status=run_status, current_node_id="implement",
                      node_state={"node_id": "implement", "entry": 9})
    db.add_all([session, run])
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main", runtime="chat", active=True))
    await db.flush()
    return run, session


@pytest.mark.asyncio
async def test_a_running_server_run_pauses_when_its_turn_was_interrupted(db: AsyncSession, auth_user: User) -> None:
    run, session = await _run_with_thread(db, auth_user)

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_STARTUP)

    assert (settlement.sessions, settlement.paused_runs) == (1, 1)
    await db.refresh(run)
    assert (run.status, run.pause_reason) == ("paused", "service_restarted")
    pause = run.node_state["pause"]
    assert pause["code"] == "interrupted_by_restart"
    assert pause["resume"] == {"kind": "restart", "node_id": "implement"}
    event = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "paused"))).scalars().one()
    assert event.detail["reason"] == "service_restarted" and event.node_id == "implement"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["device_thread", "run_waiting", "session_not_running"])
async def test_other_runs_are_left_as_they_are(db: AsyncSession, auth_user: User, case: str) -> None:
    run, _session = await _run_with_thread(
        db, auth_user, device=case == "device_thread",
        run_status="waiting" if case == "run_waiting" else "running",
        session_status="active" if case == "session_not_running" else "running",
    )

    settlement = await settle_interrupted_turns(db, trigger=TRIGGER_STARTUP)

    assert settlement.paused_runs == 0
    await db.refresh(run)
    assert run.pause_reason is None
    assert run.status == ("waiting" if case == "run_waiting" else "running")
