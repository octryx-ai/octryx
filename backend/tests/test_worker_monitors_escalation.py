"""A worker monitor records health metrics and events, respects the autonomy gate with the correct escalation, and the cost, log and security monitors count the Workspace's session events."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

import app.services.worker_monitor_service as worker_monitor_service_module
from app.models import (
    AgentWorker,
    Project,
    User,
    WorkerMonitor,
    WorkerMonitorEvent,
    WorkerOnboarding,
    WorkerRuntimeState,
    WorkerTrustEvent,
)
from app.services.worker_monitor.evaluation import _evaluate_monitor_value
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_worker_monitor_worker_health_metrics_and_event_persistence(client, auth_headers, db):
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Metrics Worker",
        role="Ops",
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(worker_id=worker.id, onboarding_status="ready")
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=3, available_slots=3
    )
    db.add(worker)
    db.add(
        WorkerMonitor(
            id=str(uuid.uuid4()),
            worker_id=worker.id,
            name="Security Alerts",
            monitor_type="security_alert",
            threshold_config={"warning": 1, "critical": 2, "sample_value": 2},
            action_on_warning="log",
            action_on_critical="log",
        )
    )
    await db.commit()

    await worker_monitor_service_module.process_due_worker_monitors(test_session_factory)

    rows = (await db.execute(select(WorkerMonitorEvent))).scalars().all()
    assert len(rows) >= 1

    health = await client.get("/api/v1/health", headers=auth_headers)
    assert health.status_code == 200
    assert "worker_monitor_worker" in health.json()["checks"]

    metrics = await client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200
    assert 'octryx_platform_component_health{component="worker_monitor_worker"' in metrics.text


@pytest.mark.asyncio
async def test_worker_monitor_respects_autonomy_gate_and_records_correct_escalation(db):
    test_session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Low Trust Worker",
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
        worker_id=worker.id, status="active", current_priority="idle", max_parallel_tasks=3, available_slots=3
    )
    monitor = WorkerMonitor(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        name="Auto Fix Gate",
        monitor_type="security_alert",
        threshold_config={"warning": 1, "critical": 2, "sample_value": 2},
        action_on_warning="log",
        action_on_critical="auto_fix",
    )
    db.add(worker)
    db.add(monitor)
    await db.commit()

    refreshed_worker = (
        await db.execute(
            select(AgentWorker)
            .options(selectinload(AgentWorker.runtime_state), selectinload(AgentWorker.onboarding))
            .where(AgentWorker.id == worker.id)
        )
    ).scalar_one()
    refreshed_monitor = await db.get(WorkerMonitor, monitor.id)
    result = await worker_monitor_service_module.evaluate_worker_monitor(
        db,
        test_session_factory,
        worker=refreshed_worker,
        monitor=refreshed_monitor,
    )

    assert result["status"] == "triggered"
    assert result["event"].triggered_action == "escalate"
    assert result["event"].session_id is None

    trust_rows = (
        (await db.execute(select(WorkerTrustEvent).where(WorkerTrustEvent.worker_id == worker.id))).scalars().all()
    )
    assert len(trust_rows) == 1
    assert trust_rows[0].event_type == "correct_escalation"


@pytest.mark.asyncio
async def test_cost_log_and_security_monitors_count_the_workspace_sessions_events(db):
    # Usage and tool calls have no Workspace column of their own; the monitors read them through their session's
    # Workspace. The security monitor counts the content-security decisions recorded for the Workspace.
    from datetime import timedelta

    from app.models import PolicyDecisionLog, Session, ToolCall, UsageEvent
    from app.services.decisions.recorder import GATE_CONTENT_SECURITY, build_gate_record

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    other = Project(id=str(uuid.uuid4()), name=f"other-{uuid.uuid4().hex[:6]}")
    db.add(other)
    mine = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id)
    theirs = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=other.id)
    db.add_all([mine, theirs])
    await db.flush()
    now = utc_now()
    db.add_all([
        *(PolicyDecisionLog(**build_gate_record(gate=GATE_CONTENT_SECURITY, outcome="denied", action="call_model",
                                                resource="model m", workspace_id=workspace_id))
          for workspace_id in (project.id, other.id)),
        ToolCall(session_id=mine.id, tool_name="t", status="error"),
        ToolCall(session_id=theirs.id, tool_name="t", status="error"),
        UsageEvent(session_id=mine.id, user_id=admin.id, cost=1, created_at=now - timedelta(hours=30)),
        UsageEvent(session_id=mine.id, user_id=admin.id, cost=2, created_at=now - timedelta(hours=1)),
        UsageEvent(session_id=theirs.id, user_id=admin.id, cost=50, created_at=now - timedelta(hours=1)),
    ])
    await db.commit()

    expected = {"security_alert": "1.0", "log_error_pattern": "1.0", "cost_anomaly": "100.0"}
    for monitor_type, value in expected.items():
        worker = AgentWorker(id=str(uuid.uuid4()), project_id=project.id, name=f"W {monitor_type}", role="Ops", is_active=True)
        monitor = WorkerMonitor(id=str(uuid.uuid4()), worker_id=worker.id, name=monitor_type, monitor_type=monitor_type,
                                threshold_config={"warning": 1}, action_on_warning="log", action_on_critical="log")
        db.add_all([worker, monitor])
        await db.commit()
        severity, detected, _, _ = await _evaluate_monitor_value(db, worker, monitor)
        assert (monitor_type, detected, severity) == (monitor_type, value, "warning")
