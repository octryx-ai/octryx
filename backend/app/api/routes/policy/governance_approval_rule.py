"""The platform approval rule (Settings › Governance › Approval rule)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import _user_is_admin
from ....services.auth import get_current_user
from ....services.governance.approval_rule import ApprovalRuleError, approval_rule_status, set_approval_rule

router = APIRouter(prefix="/api/v1/admin/governance", tags=["governance"])


class ApprovalRuleRequest(BaseModel):
    rule: str = Field(min_length=1, max_length=40)


@router.get("/approval-rule")
async def get_approval_rule(
    _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await approval_rule_status(db)


@router.put("/approval-rule")
async def put_approval_rule(
    body: ApprovalRuleRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail="Platform admin role required")
    try:
        await set_approval_rule(db, rule=body.rule, actor_id=user.id)
    except ApprovalRuleError as error:
        raise HTTPException(status_code=422, detail={"code": error.code}) from None
    await db.commit()
    return await approval_rule_status(db)
