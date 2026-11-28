import uuid

import pytest
from sqlalchemy import select

from app.models import AgentWorker, Project, Session, WorkerDelegation
from app.services.coordinator_contract import load_coordinator_state_contract


@pytest.mark.asyncio
async def test_load_coordinator_state_contract_rolls_up_worker_delegation_state(db, auth_user):
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
        metadata_={"title": "Coordinator Delegation Root"},
    )
    delegated_a = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        status="completed",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
        metadata_={"trigger": "worker_delegation"},
    )
    delegated_b = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
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

    payload = await load_coordinator_state_contract(db, session_id=root_session.id)

    assert payload is not None
    assert payload.coordinator_mode == "worker_delegation"
    assert payload.aggregate_status == "completed_with_failures"
    assert payload.child_session_ids == [delegated_a.id, delegated_b.id]
    assert payload.delegated_session_ids == [delegated_a.id, delegated_b.id]
    assert payload.delegation_ids == [delegation_a.id, delegation_b.id]
    assert payload.synthesis_ready is True
    assert payload.can_stop is False
