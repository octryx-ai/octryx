"""Session coordinator control over the API: continue delegates along the root lineage, stop cancels a running root, and stop refuses worker-delegation mode."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project, Session, WorkerDelegation


@pytest.mark.asyncio
async def test_post_session_coordinator_control_stop_rejects_worker_delegation_mode(client, auth_headers, db, auth_user):
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
        user_id=auth_user.id,
        project_id=project.id,
        status="active",
        metadata_={"title": "Coordinator Root"},
    )
    delegated_session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
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
