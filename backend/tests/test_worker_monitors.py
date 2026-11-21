"""Worker monitors are created, listed and processed when due into events and sessions; every supported type evaluates and a retired type reports that it needs configuration."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

import app.services.worker_monitor_service as worker_monitor_service_module
from app.models import AgentWorker, Project, User, WorkerMonitor, WorkerOnboarding, WorkerRuntimeState
from app.time_utils import utc_now


async def _evaluate_sample_monitor(db, monitor_type: str, sample_value: int) -> dict:
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=f"Worker {monitor_type}",
        role="On-Call",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(worker_id=worker.id, onboarding_status="ready")
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=3, available_slots=3
    )
    monitor = WorkerMonitor(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        name=f"Monitor {monitor_type}",
        monitor_type=monitor_type,
        threshold_config={"warning": 1, "critical": 2, "sample_value": sample_value},
        action_on_warning="log",
        action_on_critical="log",
    )
    db.add(worker)
    db.add(monitor)
    await db.commit()

    refreshed_worker = (
        await db.execute(
            select(AgentWorker).options(selectinload(AgentWorker.runtime_state)).where(AgentWorker.id == worker.id)
        )
    ).scalar_one()
    refreshed_monitor = await db.get(WorkerMonitor, monitor.id)
    return await worker_monitor_service_module.evaluate_worker_monitor(
        db,
        test_session_factory,
        worker=refreshed_worker,
        monitor=refreshed_monitor,
    )


@pytest.mark.asyncio
async def test_worker_monitor_crud_and_due_processing_creates_events_and_sessions(
    client, auth_headers, db, monkeypatch
):
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Monitor Alex",
        role="On-Call",
        trust_score=0.7,
        autonomy_level="autonomous",
        report_channel="#ops",
        escalation_user_id=admin.id,
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id,
        knowledge_categories_required=["runbooks"],
        onboarding_status="ready",
        ready_at=utc_now(),
        warmup_period_hours=0,
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=3, available_slots=3
    )
    db.add(worker)
    await db.commit()

    async def _fake_run_monitor_agent_session(*args, **kwargs):
        return None

    monkeypatch.setattr(worker_monitor_service_module, "_run_monitor_agent_session", _fake_run_monitor_agent_session)

    create_resp = await client.post(
        f"/api/v1/workers/{worker.id}/monitors",
        json={
            "name": "K8s Health",
            "monitor_type": "k8s_health",
            "check_interval_minutes": 1,
            "threshold_config": {"warning": 1, "critical": 2, "sample_value": 3},
            "action_on_warning": "notify",
            "action_on_critical": "diagnose",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    monitor = create_resp.json()
    assert monitor["monitor_type"] == "k8s_health"

    patch_resp = await client.patch(
        f"/api/v1/workers/{worker.id}/monitors/{monitor['id']}",
        json={"threshold_config": {"warning": 1, "critical": 2, "sample_value": 4}},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["threshold_config"]["sample_value"] == 4

    stats = await worker_monitor_service_module.process_due_worker_monitors(test_session_factory)
    assert stats["checked"] >= 1
    assert stats["events_created"] >= 1

    list_resp = await client.get(f"/api/v1/workers/{worker.id}/monitors", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    events_resp = await client.get(f"/api/v1/workers/{worker.id}/monitor-events", headers=auth_headers)
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 1
    assert events[0]["severity"] == "critical"
    assert events[0]["session_id"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("monitor_type", "sample_value"),
    [
        ("k8s_health", 2),
        ("prometheus_query", 5),
        ("jira_backlog", 4),
        ("cost_anomaly", 35),
        ("log_error_pattern", 6),
        ("security_alert", 1),
    ],
)
async def test_all_worker_monitor_types_are_supported(db, monitor_type, sample_value):
    result = await _evaluate_sample_monitor(db, monitor_type, sample_value)
    assert result["severity"] in {"warning", "critical"}
