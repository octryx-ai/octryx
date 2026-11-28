from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.worker_monitor.crud import (
    create_worker_monitor,
    list_worker_monitor_events,
    list_worker_monitors,
    patch_worker_monitor,
)

from ....db import get_db
from ....models import User
from ....schemas.operations.worker import (
    WorkerMonitorCreateRequest,
    WorkerMonitorEventResponse,
    WorkerMonitorPatchRequest,
    WorkerMonitorResponse,
)
from ....services.auth import get_current_user

router = APIRouter()


@router.get("/{worker_id}/monitors", response_model=list[WorkerMonitorResponse])
async def get_worker_monitors(
    worker_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_monitors(db, worker_id=worker_id, current_user=current_user)


@router.post("/{worker_id}/monitors", response_model=WorkerMonitorResponse)
async def post_worker_monitor(
    worker_id: str,
    body: WorkerMonitorCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_worker_monitor(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.patch("/{worker_id}/monitors/{monitor_id}", response_model=WorkerMonitorResponse)
async def patch_worker_monitor_endpoint(
    worker_id: str,
    monitor_id: str,
    body: WorkerMonitorPatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await patch_worker_monitor(
        db,
        worker_id=worker_id,
        monitor_id=monitor_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/{worker_id}/monitor-events", response_model=list[WorkerMonitorEventResponse])
async def get_worker_monitor_events(
    worker_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_monitor_events(db, worker_id=worker_id, current_user=current_user, limit=limit)
