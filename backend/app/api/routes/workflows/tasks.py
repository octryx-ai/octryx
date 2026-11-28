import asyncio
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Task, TaskQueueEntry, TaskRun, User
from ....schemas.operations.task import TaskCreate, TaskResponse, TaskRunResponse
from ....services.access_control import assert_user_owns_resource, require_project_access
from ....services.admin.task._dispatch_binding import require_bound_state
from ....services.auth import get_current_user
from ....services.data_access import Viewer, run_as
from ....services.notification_delivery.access import require_admin_user
from ....services.run_admission.action_config import require_action_config
from ....services.run_capability.schedule_capability import require_valid_schedule_capability
from ....services.task_schedule_authoring import require_task_schedule

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# Scheduler reload rate limit — prevent abuse via repeated reloads.
# State is guarded by an asyncio.Lock so concurrent requests cannot race the
# read-check-write sequence and each obtain a slot.
_scheduler_reload_lock = asyncio.Lock()
_scheduler_reload_last_call: datetime | None = None
_scheduler_reload_cooldown = timedelta(seconds=30)


async def _acquire_scheduler_reload_slot(now: datetime | None = None) -> bool:
    # Atomic claim: ``True`` records the call time, ``False`` while still within the cooldown.
    global _scheduler_reload_last_call
    async with _scheduler_reload_lock:
        current = now if now is not None else datetime.utcnow()
        last_call = _scheduler_reload_last_call
        if last_call is not None and (current - last_call) < _scheduler_reload_cooldown:
            return False
        _scheduler_reload_last_call = current
        return True


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    project_id: str | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Task).where(Task.owner_id == current_user.id)
    if project_id:
        query = query.where(Task.project_id == project_id)
    if is_active is not None:
        query = query.where(Task.is_active == is_active)
    result = await db.execute(query.order_by(Task.created_at.desc()))
    tasks = result.scalars().all()
    return [
        TaskResponse(
            id=t.id,
            project_id=t.project_id,
            name=t.name,
            description=t.description or "",
            task_type=t.task_type,
            agent_type=t.agent_type,
            schedule=t.schedule,
            config=t.config or {},
            is_active=t.is_active,
            owner_id=t.owner_id,
            created_at=t.created_at.isoformat(),
            dispatch_binding=t.dispatch_binding,
        )
        for t in tasks
    ]


@router.post("", response_model=TaskResponse)
async def create_task(
    body: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    require_valid_schedule_capability(body.config)
    await require_action_config(db, body.config)  # an agent or a workflow, never both
    await require_task_schedule(body.schedule)
    await require_bound_state(
        db, binding=body.dispatch_binding, task_type=body.task_type, config=body.config,
        owner_id=current_user.id, project_id=body.project_id, has_enabled_steps=False,
    )
    task = Task(
        id=str(uuid.uuid4()),
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        task_type=body.task_type,
        agent_type=body.agent_type,
        schedule=body.schedule,
        config=body.config,
        owner_id=current_user.id,
        dispatch_binding=body.dispatch_binding,
    )
    db.add(task)
    await db.commit()
    return TaskResponse(
        id=task.id,
        project_id=task.project_id,
        name=task.name,
        description=task.description or "",
        task_type=task.task_type,
        agent_type=task.agent_type,
        schedule=task.schedule,
        config=task.config or {},
        is_active=task.is_active,
        owner_id=task.owner_id,
        created_at=task.created_at.isoformat(),
        dispatch_binding=task.dispatch_binding,
    )


@router.get("/{task_id}/runs", response_model=list[TaskRunResponse])
async def list_task_runs(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task_obj = task_row.scalar_one_or_none()
    if not task_obj:
        raise HTTPException(status_code=404, detail="Task not found")
    await assert_user_owns_resource(
        task_obj.owner_id, current_user.id, db,
        error_detail="Access denied: you do not own this task.",
    )
    result = await db.execute(
        select(TaskRun, TaskQueueEntry)
        .outerjoin(TaskQueueEntry, TaskQueueEntry.task_run_id == TaskRun.id)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.started_at.desc().nullslast(), TaskQueueEntry.queued_at.desc().nullslast())
        .limit(50)
    )
    runs = result.all()
    return [
        TaskRunResponse(
            id=r.id,
            task_id=r.task_id,
            session_id=r.session_id,
            status=r.status,
            started_by=r.started_by,
            input=r.input_ or {},
            output=r.output,
            error=r.error,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            queue_priority=q.priority if q else None,
            queued_at=q.queued_at.isoformat() if q and q.queued_at else None,
            queue_started_at=q.started_at.isoformat() if q and q.started_at else None,
            estimated_wait_seconds=q.estimated_wait_seconds if q else None,
        )
        for r, q in runs
    ]


async def _running_run_answer(db: AsyncSession, task: Task) -> dict | None:
    running_run = (
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == task.id, TaskRun.status == "running")
                .order_by(TaskRun.started_at.desc().nullslast())
            )
        )
        .scalars()
        .first()
    )
    if running_run is None:
        return None
    return {
        "status": "running",
        "task_id": task.id,
        "task_run_id": running_run.id,
        "session_id": running_run.session_id,
    }


async def _queued_run_answer(db: AsyncSession, payload: dict, task_id: str) -> dict:
    for _ in range(100):
        await asyncio.sleep(0.02)
        db.expire_all()
        queued_run = await db.get(TaskRun, payload["task_run_id"])
        if queued_run is None:
            break
        run_status = str(queued_run.status or "").strip().lower()
        if queued_run.session_id or run_status not in {"queued", "running"}:
            return {
                "status": "running" if run_status in {"queued", "running"} else run_status,
                "task_id": task_id,
                "task_run_id": queued_run.id,
                "session_id": queued_run.session_id,
            }

    return payload


@router.post("/{task_id}/trigger", response_model=dict)
async def trigger_task(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a task execution."""
    resolved_task_id = task_id
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await assert_user_owns_resource(
        task.owner_id, current_user.id, db,
        error_detail="Access denied: you do not own this task.",
    )
    resolved_task_id = task.id

    running = await _running_run_answer(db, task)
    if running is not None:
        return running

    from ....runtime_lifecycle import get_task_scheduler

    task_scheduler = get_task_scheduler()
    request_session_factory = getattr(request.app.state, "async_session_factory", None)
    if request_session_factory is not None:
        task_scheduler.set_session_factory(request_session_factory)

    from ....scheduler.dispatch.backend import TASK_WORKSPACE_REQUIRED, TaskNotRunnableError
    from ....services.run_admission.denials import workspace_required_detail

    try:
        payload = await task_scheduler.run_task_now(
            task.id,
            started_by=current_user.id,
            allow_inactive=True,
        )
    except TaskNotRunnableError as exc:
        if exc.reason != TASK_WORKSPACE_REQUIRED:
            raise
        raise HTTPException(status_code=409, detail=workspace_required_detail(str(exc))) from None
    if payload.get("status") != "queued":
        return payload

    # "Run now" executes in this process; the claim keeps the platform worker's dispatcher
    # (another process) from starting the same queued run too. Lost claim: it runs there.
    if await task_scheduler.claim_queued_run(payload["task_run_id"]):
        run = task_scheduler._execute_task(resolved_task_id, trigger_type="manual", task_run_id=payload["task_run_id"])
        asyncio.create_task(run_as(Viewer(current_user.id), run))
    return await _queued_run_answer(db, payload, resolved_task_id)


@router.get("/scheduler/jobs", response_model=list[dict])
async def list_scheduler_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active scheduler jobs. They live in the process that holds the scheduler lease: this one, else the
    platform worker (read from the database)."""
    from ....runtime_lifecycle import get_task_scheduler
    from ....scheduler.coordination.registered_jobs import registered_jobs_from_database

    task_scheduler = get_task_scheduler()
    coordinator = getattr(task_scheduler, "_coordinator", None)
    if coordinator is None or coordinator.is_owner:
        return task_scheduler.get_jobs()
    return await registered_jobs_from_database(db)


@router.post("/scheduler/reload", response_model=dict)
async def reload_scheduler(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reload all scheduled tasks from DB."""
    await require_admin_user(db, current_user)

    if not await _acquire_scheduler_reload_slot():
        raise HTTPException(
            status_code=429,
            detail="Scheduler reload is rate-limited. Please wait before retrying.",
        )

    from sqlalchemy import select

    from ....runtime_lifecycle import get_task_scheduler

    # The lease owner re-registers every job from the stored rows.
    get_task_scheduler().request_reconcile()
    result = await db.execute(select(Task.id).where(Task.is_active.is_(True), Task.schedule.isnot(None)))
    return {"reloaded": len(result.scalars().all())}
