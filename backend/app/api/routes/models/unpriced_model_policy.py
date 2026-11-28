"""Runtime → Limits & budgets: what a cost cap does with an unpriced model (``budget/unpriced_guard``)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import AuditLog, User
from ....services.auth.admin_principal import get_current_admin_user
from ....services.budget.unpriced_guard import set_unpriced_model_policy, unpriced_model_policy

router = APIRouter(prefix="/api/v1/admin/runtime/unpriced-model-policy", tags=["runtime"])


class UnpricedModelPolicyBody(BaseModel):
    policy: Literal["block", "warn"]


@router.get("")
async def get_policy(_admin: User = Depends(get_current_admin_user), db: AsyncSession = Depends(get_db)):
    return {"policy": await unpriced_model_policy(db)}


@router.put("")
async def put_policy(
    body: UnpricedModelPolicyBody,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    before = await unpriced_model_policy(db)
    after = await set_unpriced_model_policy(db, body.policy)
    db.add(AuditLog(user_id=admin.id, action="runtime.unpriced_model_policy.updated", resource_type="system_config",
                    resource_id="agent.unpriced_model_policy", details={"before": before, "after": after}))
    await db.commit()
    return {"policy": after}
