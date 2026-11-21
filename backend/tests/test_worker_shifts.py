import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.services.worker_shift_service as worker_shift_service_module
from app.models import (
    AgentWorker,
    Project,
    WorkerDailyAgenda,
    WorkerMonitor,
    WorkerMonitorEvent,
    WorkerOnboarding,
    WorkerRuntimeState,
    WorkerShift,
    WorkerTrustEvent,
)
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_worker_shift_api_agenda_and_handover(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Shift Alex",
        role="Ops",
        schedule_type="business_hours",
        work_hours_start=None,
        work_hours_end=None,
        report_schedule="09:00",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=3, available_slots=3
    )
    monitor = WorkerMonitor(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        name="Backlog Monitor",
        monitor_type="jira_backlog",
        threshold_config={"warning": 1, "critical": 2, "sample_value": 2},
        action_on_warning="log",
        action_on_critical="log",
    )
    db.add_all([worker, monitor])
    await db.commit()

    shift_resp = await client.post(
        f"/api/v1/workers/{worker.id}/shifts/start",
        json={"shift_type": "morning"},
        headers=auth_headers,
    )
    assert shift_resp.status_code == 200, shift_resp.text
    shift = shift_resp.json()
    assert shift["status"] == "active"
    assert shift["shift_type"] == "morning"

    agenda_resp = await client.get(f"/api/v1/workers/{worker.id}/agenda", headers=auth_headers)
    assert agenda_resp.status_code == 200, agenda_resp.text
    agenda = agenda_resp.json()
    assert len(agenda["agenda_items"]) >= 1
    assert any(item["type"] == "monitor" for item in agenda["agenda_items"])

    db.add(
        WorkerMonitorEvent(
            id=str(uuid.uuid4()),
            monitor_id=monitor.id,
            worker_id=worker.id,
            severity="critical",
            detected_value="2.0",
            threshold_value="warning=1.0, critical=2.0",
            triggered_action="log",
        )
    )
    db.add(
        WorkerTrustEvent(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            event_type="success",
            trust_delta=0.05,
            new_trust_score=0.75,
            reason="Handled queue cleanly",
        )
    )
    await db.commit()

    handover_resp = await client.post(
        f"/api/v1/workers/{worker.id}/shifts/{shift['id']}/handover",
        json={},
        headers=auth_headers,
    )
    assert handover_resp.status_code == 200, handover_resp.text
    handed_over = handover_resp.json()
    assert handed_over["status"] == "handed_over"
    assert handed_over["shift_end"] is not None
    assert len(handed_over["open_items"]) >= 1
    assert len(handed_over["completed_items"]) >= 1
    assert "Shift handover for Shift Alex" in handed_over["handover_summary"]


@pytest.mark.asyncio
async def test_worker_agenda_worker_health_metrics_and_generation(client, auth_headers, db):
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Agenda Worker",
        role="On-Call",
        schedule_type="always_on",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=2, available_slots=2
    )
    db.add(worker)
    await db.commit()

    stats = await worker_shift_service_module.process_due_worker_agendas(test_session_factory)
    assert stats["workers_checked"] >= 1
    assert stats["agendas_created"] >= 1
    assert stats["shifts_started"] >= 1

    agenda_row = (
        await db.execute(select(WorkerDailyAgenda).where(WorkerDailyAgenda.worker_id == worker.id))
    ).scalar_one()
    shift_row = (
        await db.execute(select(WorkerShift).where(WorkerShift.worker_id == worker.id, WorkerShift.status == "active"))
    ).scalar_one()
    assert agenda_row is not None
    assert shift_row is not None

    health = await client.get("/api/v1/health", headers=auth_headers)
    assert health.status_code == 200
    assert "worker_agenda_worker" in health.json()["checks"]

    metrics = await client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200
    assert 'octryx_platform_component_health{component="worker_agenda_worker"' in metrics.text
