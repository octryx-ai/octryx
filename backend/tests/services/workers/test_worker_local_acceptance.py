import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.services.worker.service as worker_service_module
from app.models import ChannelConfig, Project, TaskQueueEntry, TaskRun, User
from app.services.tool_config import upsert_tool_config
from app.services.worker.policy import DEFAULT_WORKER_KNOWLEDGE_CATEGORIES
from app.services.worker_pool.state import claim_worker_assignment, release_worker_assignment
from app.time_utils import utc_now
from tests.services.workers.worker_local_acceptance_support import (
    acceptance_worker_payload,
    load_worker_with_runtime,
    mark_onboarding_ready,
    seed_full_worker_with_pending_entry,
    seed_queued_diagnosis_task,
    stub_queue_scheduler,
)


async def _login_headers(client, username: str, password: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_acceptance_readiness_context(db, project: Project) -> None:
    # Connections come from Workspace tool entries, never Project.config.
    await upsert_tool_config(db, tool_name="jira", project_id=project.id, is_active=True,
                             config={"jira_url": "https://jira.example.test"})
    await upsert_tool_config(db, tool_name="kubernetes", project_id=project.id, is_active=True,
                             config={"k8s_context": "local-acceptance", "k8s_namespace": "acme-orders"})
    db.add_all(
        [
            ChannelConfig(
                plugin_id="slack",
                name="Acceptance Slack",
                project_id=project.id,
                enabled=True,
                config="{}",
            ),
        ]
    )
    await db.commit()


def _stub_connector_test(monkeypatch):
    async def fake_connector_test(name: str, config: dict):
        assert not any("token" in key or "password" in key for key in config)
        return {"ok": True, "summary": f"{name} local acceptance ok"}

    monkeypatch.setattr(worker_service_module, "run_connector_connection_test", fake_connector_test)


async def _load_queue_entry(db, task_run_id):
    return (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run_id))).scalar_one()


def _assert_onboarding_fails_closed(worker_payload):
    # No governed source maps onto the required knowledge categories yet: readiness fails closed.
    assert worker_payload["onboarding"]["onboarding_status"] == "failed"
    assert worker_payload["onboarding"]["knowledge_gaps"] == DEFAULT_WORKER_KNOWLEDGE_CATEGORIES
    assert worker_payload["runtime_state"]["available_slots"] == 2
    assert {item["connector"] for item in worker_payload["onboarding"]["connector_checks"]} == {
        "jira",
        "kubernetes",
    }


@pytest.mark.asyncio
async def test_worker_local_acceptance_happy_path_create_dispatch_report_and_visibility(
    client,
    auth_headers,
    db,
    monkeypatch, auth_user,
):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    await _seed_acceptance_readiness_context(db, project)

    _stub_connector_test(monkeypatch)

    create_response = await client.post(
        "/api/v1/workers",
        json=acceptance_worker_payload(project.id, auth_user.id),
        headers=auth_headers,
    )
    assert create_response.status_code == 200, create_response.text
    worker_payload = create_response.json()
    _assert_onboarding_fails_closed(worker_payload)
    # Dispatch only picks ready workers, so the rest of the path runs against an explicitly ready worker.
    await mark_onboarding_ready(db, worker_payload["id"])

    task = await seed_queued_diagnosis_task(db, project, auth_user)

    scheduler, dispatched_calls = stub_queue_scheduler(monkeypatch, db)

    run_payload = await scheduler.run_task_now(task.id, started_by=auth_user.id)
    queue_entry = await _load_queue_entry(db, run_payload["task_run_id"])
    assert queue_entry.queue_backend == "database"
    assert queue_entry.required_domain == "kubernetes"
    assert queue_entry.status == "pending"

    dispatched = await scheduler._dispatch_queued_runs_once()
    assert dispatched == 1
    await asyncio.sleep(0)

    await db.refresh(queue_entry)
    worker = await load_worker_with_runtime(db, worker_payload["id"])
    runtime_state = worker.runtime_state
    assert runtime_state is not None
    assert dispatched_calls == [(worker.id, "kubernetes")]
    assert queue_entry.status == "in_progress"
    assert queue_entry.assigned_to == worker.id
    assert runtime_state.active_tasks_count == 1
    assert runtime_state.available_slots == 1

    await _complete_and_release(db, worker, queue_entry, runtime_state)
    assert queue_entry.status == "completed"
    assert runtime_state.active_tasks_count == 0
    assert runtime_state.available_slots == 2
    assert runtime_state.tasks_completed_today >= 1

    await _assert_report_health_and_metrics(client, auth_headers, worker.id)


async def _complete_and_release(db, worker, queue_entry, runtime_state):
    task_run = await db.get(TaskRun, queue_entry.task_run_id)
    assert task_run is not None
    task_run.status = "completed"
    task_run.completed_at = utc_now()
    await release_worker_assignment(
        db,
        worker_id=worker.id,
        queue_entry=queue_entry,
        task_run=task_run,
        success=True,
        required_domain="kubernetes",
    )
    await db.commit()
    await db.refresh(queue_entry)
    await db.refresh(runtime_state)


async def _assert_report_health_and_metrics(client, auth_headers, worker_id):
    report_response = await client.post(f"/api/v1/workers/{worker_id}/reports/generate", headers=auth_headers)
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["report_type"] == "daily"
    assert report["delivery_status"] == "sent"
    assert report["delivered_to"] == ["slack:#acceptance"]

    health_response = await client.get("/api/v1/health", headers=auth_headers)
    assert health_response.status_code == 200
    health_checks = health_response.json()["checks"]
    assert "scheduler" in health_checks
    assert "worker_report_worker" in health_checks

    metrics_response = await client.get("/metrics", headers=auth_headers)
    assert metrics_response.status_code == 200
    assert 'octryx_platform_component_health{component="worker_report_worker"' in metrics_response.text


@pytest.mark.asyncio
async def test_worker_local_acceptance_denied_admin_and_capacity_failure(client, auth_headers, db):
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "worker-acceptance-user",
            "email": "worker-acceptance-user@example.test",
            "password": "testpass123",
            "display_name": "Worker Acceptance User",
        },
        headers=auth_headers,
    )
    assert register_response.status_code == 200, register_response.text
    user_headers = await _login_headers(client, "worker-acceptance-user", "testpass123")

    denied_response = await client.get("/api/v1/workers", headers=user_headers)
    assert denied_response.status_code == 403
    assert denied_response.json()["error"] == "Admin access required"

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker, task_run, queue_entry = await seed_full_worker_with_pending_entry(db, project, admin)
    worker = await load_worker_with_runtime(db, worker.id)
    runtime_state = worker.runtime_state
    assert runtime_state is not None

    with pytest.raises(HTTPException) as exc_info:
        await claim_worker_assignment(db, worker=worker, queue_entry=queue_entry, task_run=task_run)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Worker has no available task slots"
    assert runtime_state.active_tasks_count == 1
    assert runtime_state.available_slots == 0
    assert queue_entry.status == "pending"
    assert queue_entry.assigned_to is None
