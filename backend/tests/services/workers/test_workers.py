import json
import uuid

import pytest
from sqlalchemy import select

import app.services.worker.service as worker_service_module
from app.models import (
    AgentWorker,
    ChannelConfig,
    Project,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.services.tool_config import upsert_tool_config
from app.services.worker.policy import DEFAULT_WORKER_KNOWLEDGE_CATEGORIES
from app.time_utils import utc_now


async def _login_headers(client, username: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_workers_api_create_list_patch_and_readiness(client, auth_headers, db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    # Connections come from Workspace tool entries, never Project.config.
    await upsert_tool_config(db, tool_name="jira", project_id=project.id, is_active=True, config={
        "jira_auth_mode": "cloud_api_token",
        "jira_url": "https://jira.example.com", "jira_email": "svc@example.com", "jira_token": "secret",
    })
    await upsert_tool_config(db, tool_name="kubernetes", project_id=project.id, is_active=True, config={
        "k8s_context": "acme-orders-prod", "k8s_namespace": "acme-orders",
    })
    db.add_all(
        [
            ChannelConfig(
                plugin_id="slack",
                name="Acme Orders Slack",
                project_id=project.id,
                enabled=True,
                config=json.dumps({"channel": "#sre-team"}),
            ),
        ]
    )
    await db.commit()

    async def _fake_connector_test(name: str, _config: dict):
        return {"ok": True, "summary": f"{name} ok", "details": {"latency_ms": 25}}

    monkeypatch.setattr(worker_service_module, "run_connector_connection_test", _fake_connector_test)

    create_resp = await client.post(
        "/api/v1/workers",
        json={
            "project_id": project.id,
            "name": "Alex",
            "role": "Senior SRE",
            "description": "24/7 digital teammate",
            "autonomy_level": "autonomous",
            "allowed_actions": ["diagnose", "comment_jira"],
            "forbidden_actions": ["delete_production_data"],
            "report_channel": "#sre-team",
            "max_parallel_tasks": 4,
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert created["name"] == "Alex"
    # No governed source maps onto the required knowledge categories yet: readiness fails closed.
    assert created["onboarding"]["onboarding_status"] == "failed"
    assert created["onboarding"]["knowledge_coverage_score"] == 0.0
    assert created["onboarding"]["knowledge_gaps"] == DEFAULT_WORKER_KNOWLEDGE_CATEGORIES
    assert {item["connector"] for item in created["onboarding"]["connector_checks"]} == {"jira", "kubernetes"}
    assert created["onboarding"]["channels_verified"][0]["status"] == "ok"
    assert created["effective_autonomy_level"] == "supervised"
    assert created["runtime_state"]["available_slots"] == 4

    list_resp = await client.get("/api/v1/workers", headers=auth_headers)
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert any(entry["id"] == created["id"] for entry in listed)

    patch_resp = await client.patch(
        f"/api/v1/workers/{created['id']}",
        json={
            "active_tasks_count": 2,
            "current_priority": "high",
            "warmup_period_hours": 0,
            "heartbeat": True,
        },
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    assert patched["runtime_state"]["active_tasks_count"] == 2
    assert patched["runtime_state"]["available_slots"] == 2
    assert patched["runtime_state"]["current_priority"] == "high"
    assert patched["runtime_state"]["last_heartbeat"] is not None
    # Readiness failed closed (no knowledge readiness source), so the warmup never starts.
    assert patched["effective_autonomy_level"] == "supervised"


@pytest.mark.asyncio
async def test_workers_api_requires_admin(client, auth_headers):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "worker-user",
            "email": "worker-user@example.com",
            "password": "testpass123",
            "display_name": "Worker User",
        },
        headers=auth_headers,
    )
    assert register_resp.status_code == 200
    user_headers = await _login_headers(client, "worker-user", "testpass123")

    resp = await client.get("/api/v1/workers", headers=user_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "Admin access required"


@pytest.mark.asyncio
async def test_refresh_all_workers_on_startup_updates_existing_workers(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project.config = {"jira_auth_mode": "bearer_pat", "jira_url": "https://jira.example.com", "jira_token": "secret"}
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Startup Alex",
        role="On-Call",
        report_channel="#ops",
        autonomy_level="semi_auto",
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id,
        knowledge_categories_required=["runbooks"],
        onboarding_status="pending",
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        active_tasks_count=1,
        max_parallel_tasks=3,
        available_slots=3,
        status="active",
    )
    db.add_all(
        [
            worker,
            ChannelConfig(
                plugin_id="slack",
                name="Ops Slack",
                project_id=project.id,
                enabled=True,
                config="{}",
            ),
        ]
    )
    await db.commit()

    async def _fake_connector_test(name: str, _config: dict):
        return {"ok": True, "summary": f"{name} ok"}

    monkeypatch.setattr(worker_service_module, "run_connector_connection_test", _fake_connector_test)

    refreshed = await worker_service_module.refresh_all_workers_on_startup(db)
    assert refreshed >= 1

    refreshed_worker = await db.get(AgentWorker, worker.id)
    assert refreshed_worker is not None
    assert refreshed_worker.onboarding.onboarding_status == "failed"
    assert refreshed_worker.onboarding.knowledge_gaps == ["runbooks"]
    assert refreshed_worker.runtime_state.available_slots == 2


@pytest.mark.asyncio
async def test_worker_trust_events_update_autonomy_and_permissions(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Trust Alex",
        role="Incident Responder",
        autonomy_level="supervised",
        trust_score=0.2,
        allowed_actions=["diagnose"],
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
        active_tasks_count=0,
        max_parallel_tasks=3,
        available_slots=3,
        status="active",
    )
    db.add(worker)
    await db.commit()

    resp = await client.post(
        f"/api/v1/workers/{worker.id}/trust-events",
        json={"event_type": "success", "trust_delta": 0.5, "reason": "Handled incident cleanly"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    trust_event = resp.json()
    assert trust_event["new_trust_score"] == 0.7

    list_resp = await client.get("/api/v1/workers", headers=auth_headers)
    assert list_resp.status_code == 200
    worker_payload = next(item for item in list_resp.json() if item["id"] == worker.id)
    assert worker_payload["effective_autonomy_level"] == "autonomous"
    assert worker_payload["effective_action_permissions"]["diagnose"] is True
    assert worker_payload["effective_action_permissions"]["auto_fix"] is False

    second_resp = await client.post(
        f"/api/v1/workers/{worker.id}/trust-events",
        json={"event_type": "failure", "trust_delta": -0.6, "reason": "Bad remediation"},
        headers=auth_headers,
    )
    assert second_resp.status_code == 200, second_resp.text
    assert second_resp.json()["new_trust_score"] == 0.1

    trust_list_resp = await client.get(f"/api/v1/workers/{worker.id}/trust-events", headers=auth_headers)
    assert trust_list_resp.status_code == 200
    trust_rows = trust_list_resp.json()
    assert len(trust_rows) == 2
    assert {row["event_type"] for row in trust_rows} == {"success", "failure"}
