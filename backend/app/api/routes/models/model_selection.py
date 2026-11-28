"""Runtime → Models → Default & fallback admin API. Transport only, platform admins only; logic in
``services/model_selection``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import _user_is_admin, require_existing_workspace, workspace_not_found
from ....services.admin.governance.admin_config_audit_service import record_admin_config_audit
from ....services.auth import get_current_user
from ....services.model_selection.explain import explain_options, explain_turn
from ....services.model_selection.page import default_and_fallback_page
from ....services.model_selection.platform_order import ModelOrderError, save_order
from ....services.model_selection.task_models import TaskModelsError, save_task_models

router = APIRouter(prefix="/api/v1/admin/model-selection", tags=["model-selection"])

ADMIN_FORBIDDEN = "Platform admin role required"


async def _admin(db: AsyncSession, user: User) -> None:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)


@router.get("")
async def get_model_selection(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    return await default_and_fallback_page(db)


@router.put("/order")
async def put_model_order(
    body: dict[str, Any] = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    try:
        change = await save_order(db, model_keys=body.get("models"), fallback=body.get("fallback"), actor_id=user.id)
    except ModelOrderError as error:
        await db.rollback()
        raise HTTPException(status_code=422, detail={"code": error.code}) from None
    record_admin_config_audit(
        db, actor_user_id=user.id, action="admin.model_selection.order_updated", resource_type="model_selection",
        resource_id="platform_order", project_id=None, before=change["before"], after=change["after"], details={},
    )
    await db.commit()
    return await default_and_fallback_page(db)


@router.put("/tasks")
async def put_task_models(
    body: dict[str, Any] = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    try:
        change = await save_task_models(db, tasks=body.get("tasks"), actor_id=user.id)
    except TaskModelsError as error:
        await db.rollback()
        raise HTTPException(status_code=422, detail={"code": error.code}) from None
    record_admin_config_audit(
        db, actor_user_id=user.id, action="admin.model_selection.task_models_updated", resource_type="model_selection",
        resource_id="task_models", project_id=None, before=change["before"], after=change["after"], details={},
    )
    await db.commit()
    return await default_and_fallback_page(db)


@router.get("/explain/options")
async def get_explain_options(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    return await explain_options(db)


@router.post("/explain")
async def post_explain(
    body: dict[str, Any] = Body(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    workspace_id = str(body.get("workspace_id") or "")
    if not workspace_id:
        raise workspace_not_found()
    await require_existing_workspace(db, user.id, workspace_id)
    return await explain_turn(
        db,
        workspace_id=workspace_id,
        person_choice=str(body.get("person_choice") or ""),
        agent_pin=str(body.get("agent_pin") or ""),
        first_fails=body.get("first_fails") is True,
    )


__all__ = ["router"]
