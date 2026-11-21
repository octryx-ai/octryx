import uuid

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project, Session, SubAgentGroup, User, WorkerDelegation
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_get_session_coordinator_status_falls_back_to_root_session(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        metadata_={"title": "Coordinator Root"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
    )
    db.add_all([root_session, child_session])
    await db.commit()

    response = await client.get(
        f"/api/v1/sessions/{child_session.id}/coordinator-status",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["root_session_id"] == root_session.id
    assert payload["coordinator_mode"] == "direct"
    assert payload["aggregate_status"] == "active"
    assert payload["child_session_ids"] == [child_session.id]
    assert payload["delegated_session_ids"] == []
    assert payload["synthesis_ready"] is True


@pytest.mark.asyncio
async def test_get_session_coordinator_status_rolls_up_sub_agent_group_state(client, auth_headers, db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="awaiting_subagents",
        metadata_={"title": "Coordinator Root"},
    )
    child_a = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
    )
    child_b = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
    )
    group = SubAgentGroup(
        id=str(uuid.uuid4()),
        parent_session_id=root_session.id,
        status="running",
        total_count=2,
        completed_count=1,
        failed_count=0,
        child_session_ids_json=[child_a.id, child_b.id],
        child_statuses_json={child_a.id: "completed"},
        created_at=utc_now(),
    )
    root_session.metadata_["current_sub_agent_group_id"] = group.id
    db.add_all([root_session, child_a, child_b, group])
    await db.commit()

    response = await client.get(
        f"/api/v1/sessions/{root_session.id}/coordinator-status",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["root_session_id"] == root_session.id
    assert payload["coordinator_mode"] == "sub_agent_group"
    assert payload["sub_agent_group_id"] == group.id
    assert payload["aggregate_status"] == "awaiting_children"
    assert payload["child_session_ids"] == [child_a.id, child_b.id]
    assert payload["can_continue"] is False
    assert payload["can_stop"] is True


@pytest.mark.asyncio
async def test_get_session_coordinator_status_rolls_up_worker_delegation_state(client, auth_headers, db):
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
        metadata_={"title": "Coordinator Delegation Root"},
    )
    delegated_a = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"trigger": "worker_delegation"},
    )
    delegated_b = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        status="error",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"trigger": "worker_delegation"},
    )
    delegation_a = WorkerDelegation(
        id=str(uuid.uuid4()),
        project_id=project.id,
        from_worker_id=source_worker.id,
        to_worker_id=target_worker.id,
        source_session_id=root_session.id,
        delegated_session_id=delegated_a.id,
        requested_action="diagnose",
        status="completed",
    )
    delegation_b = WorkerDelegation(
        id=str(uuid.uuid4()),
        project_id=project.id,
        from_worker_id=source_worker.id,
        to_worker_id=target_worker.id,
        source_session_id=root_session.id,
        delegated_session_id=delegated_b.id,
        requested_action="diagnose",
        status="failed",
    )
    db.add_all(
        [
            source_worker,
            target_worker,
            root_session,
            delegated_a,
            delegated_b,
            delegation_a,
            delegation_b,
        ]
    )
    await db.commit()

    response = await client.get(
        f"/api/v1/sessions/{root_session.id}/coordinator-status",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["root_session_id"] == root_session.id
    assert payload["coordinator_mode"] == "worker_delegation"
    assert payload["aggregate_status"] == "completed_with_failures"
    assert payload["child_session_ids"] == [delegated_a.id, delegated_b.id]
    assert payload["delegated_session_ids"] == [delegated_a.id, delegated_b.id]
    assert payload["delegation_ids"] == [delegation_a.id, delegation_b.id]
    assert payload["synthesis_ready"] is True
    assert payload["can_continue"] is True
    assert payload["can_stop"] is False
