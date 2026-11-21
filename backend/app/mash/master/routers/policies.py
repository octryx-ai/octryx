"""MASH policy management routes.

GET    /mash/v1/policies
POST   /mash/v1/policies
PUT    /mash/v1/policies/{key}
DELETE /mash/v1/policies/{key}
POST   /mash/v1/policies/{key}/assign
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from ....db import get_db
from ..services.policy_service import (
    assign_policy,
    create_policy,
    delete_policy,
    list_policies,
    update_policy,
)
from .auth import require_mash_token

router = APIRouter(prefix="/mash/v1/policies", tags=["mash-policies"])


class PolicyCreateRequest(BaseModel):
    key: str
    name: str
    policy_type: str
    rules: dict[str, Any]
    description: str | None = None
    priority: int = 0


class PolicyUpdateRequest(BaseModel):
    name: str | None = None
    rules: dict[str, Any] | None = None
    priority: int | None = None
    status: str | None = None


class PolicyAssignRequest(BaseModel):
    platform_id: str


@router.get("")
async def policy_list(
    token: dict[str, Any] = Depends(require_mash_token),
    db: AsyncSession = Depends(get_db),
):
    return JSONResponse(await list_policies(db))


@router.post("")
async def policy_create(
    payload: PolicyCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_policy(
            db,
            key=payload.key,
            name=payload.name,
            policy_type=payload.policy_type,
            rules=payload.rules,
            description=payload.description,
            priority=payload.priority,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(result, status_code=201)


@router.put("/{key}")
async def policy_update(
    key: str,
    payload: PolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await update_policy(
            db,
            key=key,
            name=payload.name,
            rules=payload.rules,
            priority=payload.priority,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse(result)


@router.delete("/{key}")
async def policy_delete(
    key: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_policy(db, key=key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse({"status": "deleted"})


@router.post("/{key}/assign")
async def policy_assign(
    key: str,
    payload: PolicyAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await assign_policy(db, policy_key=key, platform_id=payload.platform_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse(result, status_code=201)
