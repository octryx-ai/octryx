from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.worker import (
    WorkerDelegationCompleteRequest,
    WorkerDelegationCreateRequest,
    WorkerDelegationRespondRequest,
    WorkerDelegationResponse,
)
from ....services.auth import get_current_user
from ....services.worker_delegation import (
    complete_worker_delegation,
    create_worker_delegation,
    list_worker_delegations,
    respond_to_worker_delegation,
)

router = APIRouter()


@router.get("/{worker_id}/delegations", response_model=list[WorkerDelegationResponse])
async def get_worker_delegations(
    worker_id: str,
    direction: str = "all",
    status: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_delegations(
        db,
        worker_id=worker_id,
        current_user=current_user,
        direction=direction,
        status_filter=status,
        limit=limit,
    )


@router.post("/{worker_id}/delegations", response_model=WorkerDelegationResponse)
async def post_worker_delegation(
    worker_id: str,
    body: WorkerDelegationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_worker_delegation(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.post("/{worker_id}/delegations/{delegation_id}/respond", response_model=WorkerDelegationResponse)
async def post_worker_delegation_response(
    worker_id: str,
    delegation_id: str,
    body: WorkerDelegationRespondRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await respond_to_worker_delegation(
        db,
        worker_id=worker_id,
        delegation_id=delegation_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.post("/{worker_id}/delegations/{delegation_id}/complete", response_model=WorkerDelegationResponse)
async def post_worker_delegation_complete(
    worker_id: str,
    delegation_id: str,
    body: WorkerDelegationCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await complete_worker_delegation(
        db,
        worker_id=worker_id,
        delegation_id=delegation_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
