"""Ready workers and queued tasks shared by the test_worker_pool_* modules."""

import uuid

from app.models import AgentWorker, Project, Task, TaskQueueEntry, TaskRun, User, WorkerOnboarding, WorkerRuntimeState
from app.time_utils import utc_now


def _ready_worker(project: Project, *, name: str = "Dispatch Alex", role: str = "SRE") -> AgentWorker:
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=name,
        role=role,
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
        active_tasks_count=0,
        max_parallel_tasks=3,
        available_slots=3,
    )
    return worker


async def _queued_task(
    db,
    *,
    project: Project,
    owner: User,
    config: dict | None = None,
    required_domain: str | None = None,
    priority: int = 5,
) -> tuple[Task, TaskQueueEntry]:
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Investigate noisy kubernetes task text",
        description="This text mentions pods but must not route by hidden keyword inference",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=owner.id,
        is_active=True,
        config=config or {},
    )
    db.add(task)
    await db.flush()
    task_run = TaskRun(
        id=str(uuid.uuid4()),
        task_id=task.id,
        session_id=None,
        status="queued",
        started_by=owner.id,
        input_={},
        started_at=None,
    )
    db.add(task_run)
    await db.flush()
    queue_entry = TaskQueueEntry(
        id=str(uuid.uuid4()),
        task_run_id=task_run.id,
        project_id=project.id,
        task_type="agent_run",
        priority=priority,
        status="pending",
        required_domain=required_domain,
    )
    db.add(queue_entry)
    await db.commit()
    return task, queue_entry
