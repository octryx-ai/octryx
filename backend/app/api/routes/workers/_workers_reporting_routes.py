from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.worker import WorkerLearningResponse, WorkerReportResponse
from ....services.auth import get_current_user
from ....services.worker_reporting import create_worker_report, list_worker_learnings, list_worker_reports

router = APIRouter()


@router.get("/{worker_id}/reports", response_model=list[WorkerReportResponse])
async def get_worker_reports(
    worker_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_reports(db, worker_id=worker_id, current_user=current_user, limit=limit)


@router.post("/{worker_id}/reports/generate", response_model=WorkerReportResponse)
async def post_worker_report(
    worker_id: str,
    report_type: str = "daily",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_worker_report(db, worker_id=worker_id, current_user=current_user, report_type=report_type)


@router.get("/{worker_id}/learnings", response_model=list[WorkerLearningResponse])
async def get_worker_learnings(
    worker_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_learnings(db, worker_id=worker_id, current_user=current_user, limit=limit)
