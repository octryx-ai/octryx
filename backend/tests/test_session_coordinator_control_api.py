"""Session coordinator control over the API: continue delegates along the root lineage, stop cancels a running root, and stop refuses worker-delegation mode."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project, Session, User, WorkerDelegation
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from app.services.session.turn_tasks import CHAT_RUN_TASKS


@pytest.mark.asyncio
async def test_post_session_coordinator_control_continue_uses_root_lineage_for_worker_delegation(
    client,
    auth_headers,
    db,
    monkeypatch,
):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    source_worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Coordinator Worker",
        role="Lead",
        is_active=True,
    )
    target_worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Delegate Worker",
        role="Responder",
        is_active=True,
    )
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="active",
        metadata_={"title": "Coordinator Root"},
    )
    delegated_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"trigger": "worker_delegation"},
    )
    delegation = WorkerDelegation(
        id=str(uuid.uuid4()),
        project_id=project.id,
        from_worker_id=source_worker.id,
        to_worker_id=target_worker.id,
        source_session_id=root_session.id,
        delegated_session_id=delegated_session.id,
        requested_action="diagnose",
        status="completed",
    )
    db.add_all([source_worker, target_worker, root_session, delegated_session, delegation])
    await db.commit()

    observed: dict[str, str] = {}

    async def fake_start_turn(request, *, session_factory=None):
        observed["session_id"] = request.session_id
        observed["prompt"] = request.prompt
        session = await db.get(Session, request.session_id)
        session.status = "running"
        set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
        await db.commit()
        return session

    monkeypatch.setattr("app.services.coordinator_control.start_turn", fake_start_turn)

    response = await client.post(
        f"/api/v1/sessions/{delegated_session.id}/coordinator-control",
        headers=auth_headers,
        json={"action": "continue"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "continue"
    assert payload["contract"]["root_session_id"] == root_session.id
    assert payload["contract"]["coordinator_mode"] == "worker_delegation"
    assert observed["session_id"] == root_session.id
    assert "worker delegation results" in observed["prompt"]


@pytest.mark.asyncio
async def test_post_session_coordinator_control_stop_cancels_running_root_session(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        metadata_={"title": "Coordinator Root"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
    )
    set_session_run_state(root_session, RUN_STATUS_IN_PROGRESS)
    db.add_all([root_session, child_session])
    await db.commit()

    cancelled = asyncio.Event()

    async def blocking_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    CHAT_RUN_TASKS[root_session.id] = asyncio.create_task(blocking_task())

    response = await client.post(
        f"/api/v1/sessions/{child_session.id}/coordinator-control",
        headers=auth_headers,
        json={"action": "stop"},
    )

    assert response.status_code == 200
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await db.refresh(root_session)
    payload = response.json()
    assert payload["action"] == "stop"
    assert payload["contract"]["root_session_id"] == root_session.id
    assert payload["contract"]["coordinator_mode"] == "direct"
    assert payload["contract"]["run_status"] == "stopped"
    assert payload["contract"]["can_continue"] is True
    assert payload["contract"]["can_stop"] is False
    assert root_session.status == "active"


@pytest.mark.asyncio
async def test_post_session_coordinator_control_stop_rejects_worker_delegation_mode(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    source_worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Coordinator Worker",
        role="Lead",
        is_active=True,
    )
    target_worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Delegate Worker",
        role="Responder",
        is_active=True,
    )
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="active",
        metadata_={"title": "Coordinator Root"},
    )
    delegated_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="active",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"trigger": "worker_delegation"},
    )
    delegation = WorkerDelegation(
        id=str(uuid.uuid4()),
        project_id=project.id,
        from_worker_id=source_worker.id,
        to_worker_id=target_worker.id,
        source_session_id=root_session.id,
        delegated_session_id=delegated_session.id,
        requested_action="diagnose",
        status="in_progress",
    )
    db.add_all([source_worker, target_worker, root_session, delegated_session, delegation])
    await db.commit()

    response = await client.post(
        f"/api/v1/sessions/{root_session.id}/coordinator-control",
        headers=auth_headers,
        json={"action": "stop"},
    )

    assert response.status_code == 409
    assert "direct parent-session runs" in response.json()["detail"]
