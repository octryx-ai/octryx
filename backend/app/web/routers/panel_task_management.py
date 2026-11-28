"""Admin panel routes for task management: tasks, runs, schedulers, steps and dependencies."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.scheduler.dispatch.backend import TASK_INACTIVE, TASK_WORKSPACE_REQUIRED, TaskNotRunnableError
from app.schemas.admin.admin_runtime_panel import ReorderRequest
from app.schemas.admin.admin_task_panel import (
    SchedulerCreateRequest,
    SchedulerPreviewRequest,
    SchedulerUpdateRequest,
    TaskCreateRequest,
    TaskDependencyUpsertRequest,
    TaskStepCreateRequest,
    TaskStepUpdateRequest,
    TaskUpdateRequest,
)
from app.services.admin.provider.admin_scheduler_service import (
    create_scheduler as admin_create_scheduler,
)
from app.services.admin.provider.admin_scheduler_service import (
    delete_scheduler as admin_delete_scheduler,
)
from app.services.admin.provider.admin_scheduler_service import (
    list_schedulers as admin_list_schedulers,
)
from app.services.admin.provider.admin_scheduler_service import (
    preview_scheduler as admin_preview_scheduler,
)
from app.services.admin.provider.admin_scheduler_service import (
    update_scheduler as admin_update_scheduler,
)
from app.services.admin.task._admin_task_dependencies import delete_task_dependency as admin_delete_task_dependency
from app.services.admin.task._admin_task_dependencies import list_task_dependencies as admin_list_task_dependencies
from app.services.admin.task._admin_task_dependencies import upsert_task_dependency as admin_upsert_task_dependency
from app.services.admin.task._admin_task_management import cancel_task_run as admin_cancel_task_run
from app.services.admin.task._admin_task_management import create_task as admin_create_task
from app.services.admin.task._admin_task_management import delete_task as admin_delete_task
from app.services.admin.task._admin_task_management import list_task_runs as admin_list_task_runs
from app.services.admin.task._admin_task_management import trigger_task as admin_trigger_task
from app.services.admin.task._admin_task_management import update_task as admin_update_task
from app.services.admin.task._admin_task_steps import create_task_step as admin_create_task_step
from app.services.admin.task._admin_task_steps import delete_task_step as admin_delete_task_step
from app.services.admin.task._admin_task_steps import list_task_steps as admin_list_task_steps
from app.services.admin.task._admin_task_steps import reorder_task_steps as admin_reorder_task_steps
from app.services.admin.task._admin_task_steps import update_task_step as admin_update_task_step
from app.services.run_admission.denials import workspace_required_detail
from app.web._helpers.api_guards import _require_admin_api

from ...services.access_control import require_existing_workspace

router = APIRouter()


@router.post("/chat/api/panel/tasks")
async def panel_create_task(
    payload: TaskCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, user.id, payload.project_id)
    return JSONResponse(await admin_create_task(db, user_id=user.id, payload=payload.model_dump()))


@router.put("/chat/api/panel/tasks/{task_id}")
async def panel_update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    changes = payload.model_dump(exclude_none=True)
    # An explicit `"schedule": null` clears the schedule (the task form sends it); other nulls stay ignored.
    if "schedule" in payload.model_fields_set and payload.schedule is None:
        changes["schedule"] = None
    return JSONResponse(await admin_update_task(db, task_id=task_id, payload=changes))


@router.delete("/chat/api/panel/tasks/{task_id}")
async def panel_delete_task(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_task(db, task_id=task_id))


ACTION_PAUSED_CODE = "action_paused"
ACTION_PAUSED_MESSAGE = "This Action is paused. Resume it before running it."


@router.post("/chat/api/panel/tasks/{task_id}/run")
async def panel_trigger_task(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    try:
        return JSONResponse(await admin_trigger_task(task_id=task_id, db=db))
    except TaskNotRunnableError as exc:
        # The typed scheduler refusal, raised before any run or queue entry is written.
        if exc.reason == TASK_INACTIVE:
            raise HTTPException(
                status_code=409, detail={"message": ACTION_PAUSED_MESSAGE, "code": ACTION_PAUSED_CODE}
            ) from None
        if exc.reason == TASK_WORKSPACE_REQUIRED:
            raise HTTPException(status_code=409, detail=workspace_required_detail(str(exc))) from None
        raise HTTPException(status_code=404, detail="Task not found") from None


@router.get("/chat/api/panel/tasks/{task_id}/runs")
async def panel_list_task_runs(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_task_runs(db, task_id=task_id))


@router.post("/chat/api/panel/tasks/{task_id}/runs/{run_id}/cancel")
async def panel_cancel_task_run(task_id: str, run_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_cancel_task_run(db, task_id=task_id, run_id=run_id))


@router.get("/chat/api/panel/schedulers")
async def panel_list_schedulers(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_schedulers(db))


@router.post("/chat/api/panel/schedulers")
async def panel_create_scheduler(
    payload: SchedulerCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_create_scheduler(db, user_id=user.id, payload=payload.model_dump()))


@router.post("/chat/api/panel/schedulers/preview")
async def panel_preview_scheduler(
    payload: SchedulerPreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_preview_scheduler(payload.model_dump()))


@router.put("/chat/api/panel/schedulers/{scheduler_id}")
async def panel_update_scheduler(
    scheduler_id: str,
    payload: SchedulerUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_scheduler(db, scheduler_id=scheduler_id, payload=payload.model_dump(exclude_none=True))
    )


@router.delete("/chat/api/panel/schedulers/{scheduler_id}")
async def panel_delete_scheduler(scheduler_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_scheduler(db, scheduler_id=scheduler_id))


@router.get("/chat/api/panel/tasks/{task_id}/steps")
async def panel_list_task_steps(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_task_steps(db, task_id=task_id))


@router.get("/chat/api/panel/tasks/{task_id}/dependencies")
async def panel_list_task_dependencies(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_task_dependencies(db, task_id=task_id))


@router.post("/chat/api/panel/tasks/{task_id}/dependencies")
async def panel_upsert_task_dependency(
    task_id: str,
    payload: TaskDependencyUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_upsert_task_dependency(
            db,
            task_id=task_id,
            depends_on_task_id=payload.depends_on_task_id,
            condition=payload.condition,
        )
    )


@router.delete("/chat/api/panel/tasks/{task_id}/dependencies/{dependency_id}")
async def panel_delete_task_dependency(
    task_id: str,
    dependency_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_task_dependency(db, task_id=task_id, dependency_id=dependency_id))


@router.post("/chat/api/panel/tasks/{task_id}/steps")
async def panel_create_task_step(
    task_id: str,
    payload: TaskStepCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_create_task_step(db, task_id=task_id, payload=payload.model_dump()))


@router.put("/chat/api/panel/tasks/{task_id}/steps/{step_id}")
async def panel_update_task_step(
    task_id: str,
    step_id: str,
    payload: TaskStepUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_task_step(
            db,
            task_id=task_id,
            step_id=step_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.delete("/chat/api/panel/tasks/{task_id}/steps/{step_id}")
async def panel_delete_task_step(task_id: str, step_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_task_step(db, task_id=task_id, step_id=step_id))


@router.post("/chat/api/panel/tasks/{task_id}/steps/reorder")
async def panel_reorder_task_steps(
    task_id: str,
    payload: ReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reorder steps. body = {"order": ["step_id1", "step_id2", ...]}"""
    await _require_admin_api(request, db)
    return JSONResponse(await admin_reorder_task_steps(db, task_id=task_id, order=payload.order))
