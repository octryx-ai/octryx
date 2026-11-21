from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.core.privacy import DeletionRequestCreate, RetentionPolicyRequest
from ...services.auth import get_current_user
from ...services.auth.admin_principal import get_current_admin_user
from ...services.privacy import (
    create_deletion_request,
    list_deletion_requests,
    list_retention_policies,
    upsert_retention_policy,
)
from ...web._helpers.permissions import require_global_admin

router = APIRouter(prefix="/admin", tags=["admin-privacy"])


@router.get("/retention-policies")
async def get_retention_policies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_global_admin(db, current_user)
    return await list_retention_policies(db)


@router.post("/retention-policies")
async def post_retention_policy(
    body: RetentionPolicyRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_global_admin(db, current_user)
    return await upsert_retention_policy(db, payload=body.model_dump())


@router.get("/deletion-requests")
async def get_deletion_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_global_admin(db, current_user)
    return await list_deletion_requests(db)


@router.post("/deletion-requests")
async def post_deletion_request(
    body: DeletionRequestCreate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_global_admin(db, current_user)
    return await create_deletion_request(
        db,
        requested_by=current_user.id,
        target_user_id=body.target_user_id,
        reason=body.reason,
    )
