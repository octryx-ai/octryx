import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.services.worker_reporting as worker_reporting_service_module
from app.models import (
    AgentWorker,
    Notification,
    Project,
    User,
    WorkerEscalation,
    WorkerMonitor,
    WorkerMonitorEvent,
    WorkerOnboarding,
    WorkerRuntimeState,
    WorkerShift,
    WorkerTrustEvent,
)
from app.time_utils import utc_now


def _build_report_worker(project, admin) -> AgentWorker:
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Report Alex",
        role="Ops",
        report_channel="slack:#ops-daily",
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
    return worker


def _build_report_activity(worker: AgentWorker) -> list:
    monitor = WorkerMonitor(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        name="Latency Monitor",
        monitor_type="datadog",
        threshold_config={"warning": 1, "critical": 2},
        action_on_warning="log",
        action_on_critical="page",
    )
    shift = WorkerShift(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        shift_type="morning",
        status="handed_over",
        completed_items=[{"type": "trust_success", "title": "Applied safe fix"}],
        open_items=[{"type": "followup", "title": "Review deployment"}],
    )
    return [
        monitor,
        shift,
        WorkerMonitorEvent(
            id=str(uuid.uuid4()),
            monitor_id=monitor.id,
            worker_id=worker.id,
            severity="critical",
            detected_value="3",
            threshold_value="2",
            triggered_action="page",
            resolution_summary="Recovered after restart",
            resolved_at=utc_now(),
        ),
        WorkerTrustEvent(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            event_type="success",
            trust_delta=0.05,
            new_trust_score=0.9,
            reason="Successful automatic mitigation for payment timeout",
        ),
        WorkerEscalation(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            reason="Escalated noisy alert",
            context_summary="The alert resolved before human action",
            human_response="Suppress this class of alert next time.",
            was_necessary=False,
        ),
    ]


@pytest.mark.asyncio
async def test_worker_reports_generate_and_notify(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    worker = _build_report_worker(project, admin)
    db.add_all([worker, *_build_report_activity(worker)])
    await db.commit()

    resp = await client.post(f"/api/v1/workers/{worker.id}/reports/generate", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["report_type"] == "daily"
    assert report["incidents_detected"] == 1
    assert report["incidents_resolved"] == 1
    assert report["incidents_escalated"] == 1
    assert report["autonomous_actions_taken"] == 1
    assert report["knowledge_entries_created"] == 0
    assert report["memory_updates"] == 0
    assert report["delivery_status"] == "sent"
    assert report["delivered_to"] == ["slack:#ops-daily"]

    reports_resp = await client.get(f"/api/v1/workers/{worker.id}/reports", headers=auth_headers)
    assert reports_resp.status_code == 200, reports_resp.text
    assert len(reports_resp.json()) == 1

    learnings_resp = await client.get(f"/api/v1/workers/{worker.id}/learnings", headers=auth_headers)
    assert learnings_resp.status_code == 200, learnings_resp.text
    learnings = learnings_resp.json()
    assert len(learnings) >= 2

    notifications = (await db.execute(select(Notification).where(Notification.user_id == admin.id))).scalars().all()
    assert any(item.title == "Worker report: Report Alex" for item in notifications)


@pytest.mark.asyncio
async def test_worker_report_worker_health_metrics_and_generation(client, auth_headers, db):
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Daily Reporter",
        role="Ops",
        report_channel="teams:ops-daily",
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
        max_parallel_tasks=2,
        available_slots=2,
    )
    db.add_all(
        [
            worker,
            WorkerTrustEvent(
                id=str(uuid.uuid4()),
                worker_id=worker.id,
                event_type="human_approved",
                trust_delta=0.1,
                new_trust_score=0.8,
                reason="Good remediation choice",
            ),
        ]
    )
    await db.commit()

    stats = await worker_reporting_service_module.process_due_worker_reports(test_session_factory)
    assert stats["workers_checked"] >= 1
    assert stats["reports_created"] >= 1
    assert stats["learnings_created"] >= 1

    reports_resp = await client.get(f"/api/v1/workers/{worker.id}/reports", headers=auth_headers)
    assert reports_resp.status_code == 200, reports_resp.text
    assert len(reports_resp.json()) == 1

    learnings_resp = await client.get(f"/api/v1/workers/{worker.id}/learnings", headers=auth_headers)
    assert learnings_resp.status_code == 200, learnings_resp.text
    assert len(learnings_resp.json()) >= 1

    health = await client.get("/api/v1/health", headers=auth_headers)
    assert health.status_code == 200
    assert "worker_report_worker" in health.json()["checks"]

    metrics = await client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200
    assert 'octryx_platform_component_health{component="worker_report_worker"' in metrics.text
