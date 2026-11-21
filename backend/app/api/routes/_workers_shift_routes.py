from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.operations.worker import (
    WorkerDailyAgendaResponse,
    WorkerShiftHandoverRequest,
    WorkerShiftResponse,
    WorkerShiftStartRequest,
)
from ...services.auth import get_current_user
from ...services.worker_shift_service import (
    get_worker_daily_agenda,
    handover_worker_shift,
    list_worker_shifts,
    start_worker_shift,
)

router = APIRouter()


@router.get("/{worker_id}/shifts", response_model=list[WorkerShiftResponse])
async def get_worker_shifts(
    worker_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_shifts(db, worker_id=worker_id, current_user=current_user, limit=limit)


@router.post("/{worker_id}/shifts/start", response_model=WorkerShiftResponse)
async def post_worker_shift_start(
    worker_id: str,
    body: WorkerShiftStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await start_worker_shift(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.post("/{worker_id}/shifts/{shift_id}/handover", response_model=WorkerShiftResponse)
async def post_worker_shift_handover(
    worker_id: str,
    shift_id: str,
    body: WorkerShiftHandoverRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await handover_worker_shift(
        db,
        worker_id=worker_id,
        shift_id=shift_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/{worker_id}/agenda", response_model=WorkerDailyAgendaResponse)
async def get_worker_agenda(
    worker_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_worker_daily_agenda(db, worker_id=worker_id, current_user=current_user)
