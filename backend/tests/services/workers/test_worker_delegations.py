import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (
    AgentWorker,
    Project,
    Session,
    WorkerDelegation,
    WorkerDomainExpertise,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.time_utils import utc_now


def _ready_worker(project_id: str, name: str, role: str, slots: int, **extra) -> AgentWorker:
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        role=role,
        is_active=True,
        **extra,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id,
        onboarding_status="ready",
        ready_at=utc_now(),
        warmup_period_hours=0,
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        max_parallel_tasks=slots,
        available_slots=slots,
    )
    return worker


async def _seed_delegation_pair(db, admin, project_id: str):
    source_worker = _ready_worker(project_id, "Delegator Alex", "Lead SRE", 2)
    target_worker = _ready_worker(
        project_id, "Responder Kim", "Kubernetes Specialist", 2, autonomy_level="autonomous", trust_score=0.9
    )
    source_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project_id,
        agent_type="diagnosis",
        status="active",
        metadata_={"title": "Delegation Source"},
    )
    db.add_all(
        [
            source_worker,
            target_worker,
            source_session,
            WorkerDomainExpertise(
                id=str(uuid.uuid4()),
                worker_id=target_worker.id,
                domain="kubernetes",
                expertise_level="expert",
                tasks_completed=12,
                success_rate=0.97,
            ),
        ]
    )
    await db.commit()
    return source_worker, target_worker, source_session


async def _load_with_runtime_state(db, worker_id: str) -> AgentWorker:
    return (
        await db.execute(
            select(AgentWorker)
            .options(selectinload(AgentWorker.runtime_state))
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one()


async def _create_and_check_delegation(client, auth_headers, db, source_worker, target_worker, source_session):
    create_resp = await client.post(
        f"/api/v1/workers/{source_worker.id}/delegations",
        json={
            "source_session_id": source_session.id,
            "required_domain": "kubernetes",
            "requested_action": "diagnose",
            "priority": 9,
            "context_summary": "Investigate repeated pod restarts in production.",
            "context_payload": {"pod": "api-7ddf7", "namespace": "acme-orders"},
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    delegation = create_resp.json()
    assert delegation["auto_selected"] is True
    assert delegation["to_worker_id"] == target_worker.id
    assert delegation["status"] == "pending"
    assert delegation["delegated_session_id"] is not None

    delegated_session = await db.get(Session, delegation["delegated_session_id"])
    assert delegated_session is not None
    assert delegated_session.parent_session_id == source_session.id
    assert delegated_session.metadata_["trigger"] == "worker_delegation"
    return delegation


async def _accept_and_check(client, auth_headers, db, target_worker, delegation) -> None:
    accept_resp = await client.post(
        f"/api/v1/workers/{target_worker.id}/delegations/{delegation['id']}/respond",
        json={"action": "accept", "response_note": "Taking over the investigation."},
        headers=auth_headers,
    )
    assert accept_resp.status_code == 200, accept_resp.text
    accepted = accept_resp.json()
    assert accepted["status"] == "accepted"
    assert accepted["response_note"] == "Taking over the investigation."

    refreshed_target = await _load_with_runtime_state(db, target_worker.id)
    assert refreshed_target.runtime_state.current_session_id == delegation["delegated_session_id"]


async def _complete_and_check(client, auth_headers, db, target_worker, delegation) -> None:
    complete_resp = await client.post(
        f"/api/v1/workers/{target_worker.id}/delegations/{delegation['id']}/complete",
        json={"status": "completed", "completion_summary": "Root cause isolated to a bad config rollout."},
        headers=auth_headers,
    )
    assert complete_resp.status_code == 200, complete_resp.text
    completed = complete_resp.json()
    assert completed["status"] == "completed"
    assert completed["completion_summary"] == "Root cause isolated to a bad config rollout."

    refreshed_delegation = await db.get(WorkerDelegation, delegation["id"])
    assert refreshed_delegation is not None
    assert refreshed_delegation.completed_at is not None

    refreshed_target = await _load_with_runtime_state(db, target_worker.id)
    await db.refresh(refreshed_target.runtime_state)
    assert refreshed_target.runtime_state.current_session_id is None
    delegated_session = await db.get(Session, delegation["delegated_session_id"])
    assert delegated_session is not None
    await db.refresh(delegated_session)
    assert delegated_session.status == "completed"


@pytest.mark.asyncio
async def test_worker_delegation_auto_select_accept_complete_and_list(client, auth_headers, db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    source_worker, target_worker, source_session = await _seed_delegation_pair(db, auth_user, project.id)

    delegation = await _create_and_check_delegation(
        client, auth_headers, db, source_worker, target_worker, source_session
    )

    incoming_resp = await client.get(
        f"/api/v1/workers/{target_worker.id}/delegations?direction=incoming",
        headers=auth_headers,
    )
    assert incoming_resp.status_code == 200, incoming_resp.text
    assert len(incoming_resp.json()) == 1

    await _accept_and_check(client, auth_headers, db, target_worker, delegation)
    await _complete_and_check(client, auth_headers, db, target_worker, delegation)


@pytest.mark.asyncio
async def test_worker_delegation_decline_and_unavailable_target_filter(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    source_worker = _ready_worker(project.id, "Delegator Sam", "Lead Ops", 2)
    blocked_target = _ready_worker(project.id, "Blocked Taylor", "Junior Responder", 1, allowed_actions=["notify"])
    available_target = _ready_worker(
        project.id, "Available Jordan", "Incident Responder", 1, autonomy_level="semi_auto"
    )
    db.add_all([source_worker, blocked_target, available_target])
    await db.commit()

    auto_resp = await client.post(
        f"/api/v1/workers/{source_worker.id}/delegations",
        json={
            "requested_action": "diagnose",
            "context_summary": "Find the only eligible worker.",
        },
        headers=auth_headers,
    )
    assert auto_resp.status_code == 200, auto_resp.text
    delegation = auto_resp.json()
    assert delegation["to_worker_id"] == available_target.id

    decline_resp = await client.post(
        f"/api/v1/workers/{available_target.id}/delegations/{delegation['id']}/respond",
        json={"action": "decline", "response_note": "Need a different skill set right now."},
        headers=auth_headers,
    )
    assert decline_resp.status_code == 200, decline_resp.text
    declined = decline_resp.json()
    assert declined["status"] == "declined"
    assert declined["response_note"] == "Need a different skill set right now."

    delegated_session = await db.get(Session, delegation["delegated_session_id"])
    assert delegated_session is not None
    assert delegated_session.status == "cancelled"
