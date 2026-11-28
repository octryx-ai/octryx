import uuid

import pytest
from sqlalchemy import select

import app.services.worker_escalation.service as worker_escalation_service
from app.models import AgentWorker, Project, User, WorkerOnboarding, WorkerRuntimeState
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_worker_escalation_rule_and_review_adjusts_trust(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Escalation Alex",
        role="Ops",
        trust_score=0.2,
        autonomy_level="supervised",
        escalation_user_id=admin.id,
        is_active=True,
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
        max_parallel_tasks=3,
        available_slots=3,
    )
    db.add(worker)
    await db.flush()
    await db.commit()  # HTTP request handlers read through separate sessions

    rule_resp = await client.post(
        f"/api/v1/workers/{worker.id}/escalation-rules",
        json={
            "trigger_condition": "autonomy gate blocked auto_fix",
            "situation_pattern": "required escalation",
            "escalate_to_user_id": admin.id,
            "escalate_via": "pagerduty",
            "priority": "high",
        },
        headers=auth_headers,
    )
    assert rule_resp.status_code == 200, rule_resp.text
    rule = rule_resp.json()
    assert rule["escalate_via"] == "pagerduty"

    # Direct service call: evaluate_worker_monitor needs separate session management.
    escalation = await worker_escalation_service.log_worker_escalation(
        db,
        worker=worker,
        reason="autonomy gate blocked auto_fix",
        context_summary="Monitor 'Auto Fix Gate' reached critical and required escalation.",
        escalation_channel="pagerduty",
    )
    await db.commit()

    list_resp = await client.get(f"/api/v1/workers/{worker.id}/escalations", headers=auth_headers)
    assert list_resp.status_code == 200
    escalations = list_resp.json()
    assert len(escalations) == 1, f"Expected 1 escalation, got {escalations}"
    assert escalations[0]["escalation_channel"] == "pagerduty"

    review_resp = await client.post(
        f"/api/v1/workers/{worker.id}/escalations/{escalation['id']}/review",
        json={"human_response": "This did not need a human", "was_necessary": False, "resolution_time_minutes": 7},
        headers=auth_headers,
    )
    assert review_resp.status_code == 200, review_resp.text
    reviewed = review_resp.json()
    assert reviewed["was_necessary"] is False
    assert reviewed["resolution_time_minutes"] == 7

    workers_resp = await client.get("/api/v1/workers", headers=auth_headers)
    assert workers_resp.status_code == 200
    worker_payload = next(item for item in workers_resp.json() if item["id"] == worker.id)
    assert worker_payload["trust_score"] < 0.2
    assert worker_payload["effective_autonomy_level"] == "supervised"
