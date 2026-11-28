import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Notification, Project, SLABreach, Task, TaskRun, User
from app.services.sla import create_sla_definition, list_sla_breaches, process_sla_breaches
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_sla_process_creates_warning_and_breach_and_notification(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="SLA Task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
    )
    db.add(task)
    await db.flush()

    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        started_by=admin.id,
        status="running",
        started_at=utc_now() - timedelta(seconds=120),
    )
    db.add(run)
    await db.commit()

    await create_sla_definition(
        db,
        payload={
            "name": "Diagnosis SLA",
            "task_id": task.id,
            "max_duration_seconds": 60,
            "alert_threshold": 0.5,
            "is_active": True,
        },
    )
    result = await process_sla_breaches(db)

    assert result["checked_runs"] >= 1
    breaches = (await db.execute(select(SLABreach).where(SLABreach.task_run_id == run.id))).scalars().all()
    breach_types = {row.breach_type for row in breaches}
    assert "warning_threshold" in breach_types
    assert "duration_exceeded" in breach_types

    notifications = (await db.execute(select(Notification).where(Notification.type == "sla.breach"))).scalars().all()
    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_sla_process_resolves_warning_when_run_finishes_in_time(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Short SLA Task",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
    )
    db.add(task)
    await db.flush()

    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        started_by=admin.id,
        status="running",
        started_at=utc_now() - timedelta(seconds=50),
    )
    db.add(run)
    await db.commit()

    await create_sla_definition(
        db,
        payload={
            "name": "Task runtime",
            "agent_type": "diagnosis",
            "max_duration_seconds": 120,
            "alert_threshold": 0.25,
            "is_active": True,
        },
    )
    first = await process_sla_breaches(db)
    assert first["breaches_created"] >= 1

    run.status = "completed"
    run.completed_at = utc_now()
    await db.commit()

    second = await process_sla_breaches(db)
    assert second["breaches_resolved"] >= 1

    rows = await list_sla_breaches(db, unresolved_only=False)
    matching = [row for row in rows if row["task_run_id"] == run.id and row["breach_type"] == "warning_threshold"]
    assert matching
    assert matching[0]["is_resolved"] is True
