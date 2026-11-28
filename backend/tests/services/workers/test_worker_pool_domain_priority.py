"""Dispatch prefers the domain expert worker and pauses low-priority work under pressure."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    AgentWorker,
    Project,
    Session,
    Task,
    TaskQueueEntry,
    TaskRun,
    UsageEvent,
    WorkerDomainExpertise,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from app.services.worker_pool.dispatch import select_dispatch_worker
from app.services.worker_pool.state import get_or_create_worker_rate_limit
from app.time_utils import utc_now


def _ready_worker(project_id: str, name: str, role: str) -> AgentWorker:
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        role=role,
        is_active=True,
    )
    worker.onboarding = WorkerOnboarding(
        worker_id=worker.id, onboarding_status="ready", ready_at=utc_now(), warmup_period_hours=0
    )
    worker.runtime_state = WorkerRuntimeState(
        worker_id=worker.id,
        status="active",
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=3,
        available_slots=3,
    )
    return worker


def _seed_workers(db, project_id: str) -> AgentWorker:
    expert = _ready_worker(project_id, "Expert Alex", "SRE")
    generalist = _ready_worker(project_id, "General Sam", "Ops")
    db.add_all(
        [
            expert,
            generalist,
            WorkerDomainExpertise(
                id=str(uuid.uuid4()),
                worker_id=expert.id,
                domain="kubernetes",
                expertise_level="expert",
                tasks_completed=20,
                success_rate=0.95,
            ),
            WorkerDomainExpertise(
                id=str(uuid.uuid4()),
                worker_id=generalist.id,
                domain="kubernetes",
                expertise_level="beginner",
                tasks_completed=2,
                success_rate=0.5,
            ),
        ]
    )
    return expert


async def _seed_queue_entry(db, task, admin, project_id: str, task_type: str, priority: int) -> TaskQueueEntry:
    run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id=None,
        status="queued",
        started_by=admin.id,
        input_={},
        started_at=None,
    )
    db.add(run)
    await db.flush()
    queue_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=run.id,
        project_id=project_id,
        task_type=task_type,
        priority=priority,
        status="pending",
        required_domain="kubernetes",
    )
    db.add(queue_entry)
    await db.commit()
    return queue_entry


async def _exceed_cost_limit(db, project_id: str, session, admin) -> None:
    rate_limit = await get_or_create_worker_rate_limit(db, project_id)
    rate_limit.max_cost_per_hour = Decimal("1.00")
    rate_limit.max_cost_per_day = Decimal("2.00")
    rate_limit.on_cost_limit = "pause_low_priority"
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=admin.id,
            provider="openai",
            model="gpt-test",
            tokens_in=100,
            tokens_out=200,
            cost=Decimal("5.00"),
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_select_dispatch_worker_prefers_domain_expert_and_pauses_low_priority(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    expert = _seed_workers(db, project.id)
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="OOMKill incident",
        description="Investigate kubernetes pod restart",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=auth_user.id,
        is_active=True,
        config={"required_domain": "kubernetes"},
    )
    session = Session(
        id=str(uuid.uuid4()), user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", status="active"
    )
    db.add_all([task, session])
    await db.flush()
    high_queue_entry = await _seed_queue_entry(db, task, auth_user, project.id, "incident", 10)

    selected, reason = await select_dispatch_worker(db, task=task, queue_entry=high_queue_entry)
    assert reason is None
    assert selected is not None
    assert selected.id == expert.id

    await _exceed_cost_limit(db, project.id, session, auth_user)

    low_queue_entry = await _seed_queue_entry(db, task, auth_user, project.id, "knowledge_sync", 2)

    selected, reason = await select_dispatch_worker(db, task=task, queue_entry=low_queue_entry)
    assert selected is None
    assert reason == "paused_due_to_rate_limit"
