"""Plans, plan decisions, redeclaration and reviewers of Work items. Included into ``secure_work.py``'s router, so its
Workspace scope dependency applies here too."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.secure_work import (
    apply_reviewer_override,
    decide_change_plan,
    generate_change_plan,
    generate_llm_work_plan,
    list_change_plan_decisions,
    list_change_plans,
    list_reviewer_overrides,
    plan_work_item_change_units,
    recommend_reviewers_for_work_item,
    redeclare_work_item,
    require_work_operator,
    require_work_reader,
)
from ....services.secure_work.access import get_scoped_change_plan, get_scoped_work_item

router = APIRouter()


@router.post("/work-items/{work_item_id}/change-units/plan")
async def post_work_item_change_unit_plan(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await plan_work_item_change_units(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/work-items/{work_item_id}/change-plans")
async def get_work_item_change_plans(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return {"items": await list_change_plans(db, work_item_id)}


@router.post("/work-items/{work_item_id}/change-plans/generate")
async def post_work_item_change_plan_generate(
    work_item_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await generate_change_plan(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result


@router.post("/work-items/{work_item_id}/work-plans/generate")
async def post_work_item_llm_work_plan_generate(
    work_item_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await generate_llm_work_plan(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload or {},
    )
    await db.commit()
    return result


@router.get("/change-plans/{change_plan_id}/decisions")
async def get_change_plan_decisions(
    change_plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_reader(db, current_user)
    await get_scoped_change_plan(db, current_user, change_plan_id)
    return {"items": await list_change_plan_decisions(db, change_plan_id)}


@router.post("/change-plans/{change_plan_id}/decision")
async def post_change_plan_decision(
    change_plan_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_change_plan(db, current_user, change_plan_id)
    result = await decide_change_plan(
        db,
        change_plan_id=change_plan_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.post("/work-items/{work_item_id}/redeclare")
async def post_work_item_redeclare(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await redeclare_work_item(
        db,
        work_item_id=work_item_id,
        current_user=current_user,
        payload=payload,
    )
    await db.commit()
    return result


@router.get("/work-items/{work_item_id}/reviewer-recommendations")
async def get_work_item_reviewer_recommendations(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    item = await get_scoped_work_item(db, current_user, work_item_id)
    return await recommend_reviewers_for_work_item(db, item.id, viewer=current_user, workspace_id=item.project_id)


@router.get("/work-items/{work_item_id}/reviewer-overrides")
async def get_work_item_reviewer_overrides(
    work_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    return {"items": await list_reviewer_overrides(db, work_item_id)}


@router.post("/work-items/{work_item_id}/reviewer-overrides")
async def post_work_item_reviewer_override(
    work_item_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_work_operator(db, current_user)
    await get_scoped_work_item(db, current_user, work_item_id)
    result = await apply_reviewer_override(db, work_item_id=work_item_id, current_user=current_user, payload=payload)
    await db.commit()
    return result
