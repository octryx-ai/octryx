from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.operations.worker import (
    WorkerCreateRequest,
    WorkerPatchRequest,
    WorkerResponse,
    WorkerTrustEventCreateRequest,
    WorkerTrustEventResponse,
)
from ...services.access_control import require_visible_workspace
from ...services.auth import get_current_user
from ...services.worker import (
    create_worker,
    create_worker_trust_event,
    list_worker_trust_events,
    list_workers,
    patch_worker,
)
from ._workers_delegation_routes import router as delegation_router
from ._workers_escalation_routes import router as escalation_router
from ._workers_monitor_routes import router as monitor_router
from ._workers_pool_routes import router as pool_router
from ._workers_reporting_routes import router as reporting_router
from ._workers_shift_routes import router as shift_router

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])
router.include_router(pool_router)
router.include_router(monitor_router)
router.include_router(delegation_router)
router.include_router(shift_router)
router.include_router(reporting_router)
router.include_router(escalation_router)


@router.get("", response_model=list[WorkerResponse])
async def get_workers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_workers(db, current_user)


@router.post("", response_model=WorkerResponse)
async def post_worker(
    body: WorkerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, body.project_id)
    return await create_worker(
        db,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.patch("/{worker_id}", response_model=WorkerResponse)
async def patch_worker_endpoint(
    worker_id: str,
    body: WorkerPatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await patch_worker(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/{worker_id}/trust-events", response_model=list[WorkerTrustEventResponse])
async def get_worker_trust_events(
    worker_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_trust_events(db, worker_id=worker_id, current_user=current_user, limit=limit)


@router.post("/{worker_id}/trust-events", response_model=WorkerTrustEventResponse)
async def post_worker_trust_event(
    worker_id: str,
    body: WorkerTrustEventCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_worker_trust_event(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
