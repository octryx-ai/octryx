from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.worker import (
    WorkerEscalationResponse,
    WorkerEscalationReviewRequest,
    WorkerEscalationRuleCreateRequest,
    WorkerEscalationRuleResponse,
)
from ....services.auth import get_current_user
from ....services.worker_escalation import (
    create_worker_escalation_rule,
    list_worker_escalation_rules,
    list_worker_escalations,
    review_worker_escalation,
)

router = APIRouter()


@router.get("/{worker_id}/escalation-rules", response_model=list[WorkerEscalationRuleResponse])
async def get_worker_escalation_rules(
    worker_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_escalation_rules(db, worker_id=worker_id, current_user=current_user)


@router.post("/{worker_id}/escalation-rules", response_model=WorkerEscalationRuleResponse)
async def post_worker_escalation_rule(
    worker_id: str,
    body: WorkerEscalationRuleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_worker_escalation_rule(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/{worker_id}/escalations", response_model=list[WorkerEscalationResponse])
async def get_worker_escalations(
    worker_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_escalations(db, worker_id=worker_id, current_user=current_user, limit=limit)


@router.post("/{worker_id}/escalations/{escalation_id}/review", response_model=WorkerEscalationResponse)
async def post_worker_escalation_review(
    worker_id: str,
    escalation_id: str,
    body: WorkerEscalationReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await review_worker_escalation(
        db,
        worker_id=worker_id,
        escalation_id=escalation_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
