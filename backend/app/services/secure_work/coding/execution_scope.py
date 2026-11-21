"""What a coding agent execution runs on: the Work Item, its approved plan, the selected units, delivery providers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    CodeRepository,
    WorkChangePlan,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from ..jira_values import string_list
from ..plans.redeclare import SUPERSEDED_UNIT_STATUS


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return item


async def _approved_plan(
    db: AsyncSession,
    item: WorkItem,
    change_plan_id: str | None,
) -> WorkChangePlan | None:
    if change_plan_id:
        plan = await db.get(WorkChangePlan, change_plan_id)
        if plan is None or plan.work_item_id != item.id:
            raise HTTPException(status_code=404, detail="Work Plan not found")
        return plan if plan.status == "approved" else None
    return (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == item.id, WorkChangePlan.status == "approved")
            .order_by(WorkChangePlan.version.desc(), WorkChangePlan.approved_at.desc())
        )
    ).scalars().first()


async def _selected_units(db: AsyncSession, item: WorkItem, raw_ids: Any) -> list[WorkItemChangeUnit]:
    ids = string_list(raw_ids)
    stmt = (
        select(WorkItemChangeUnit)
        .where(
            WorkItemChangeUnit.work_item_id == item.id,
            WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
        )
        .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
    )
    if ids:
        stmt = stmt.where(WorkItemChangeUnit.id.in_(ids))
    return list((await db.execute(stmt)).scalars().all())


async def _delivery_context(
    db: AsyncSession, *, item: WorkItem, units: list[WorkItemChangeUnit]
) -> dict[str, str]:
    """Resolve the delivery providers for this run.

    The source-control provider comes from the change units' repository
    profiles; it is only set when every unit agrees on one provider. The
    ticket provider is the work item's source system.
    """
    profile_ids = {
        str(unit.repository_profile_id)
        for unit in units or []
        if getattr(unit, "repository_profile_id", None)
    }
    providers: set[str] = set()
    if profile_ids:
        rows = (
            await db.execute(
                select(CodeRepository.provider)
                .join(WorkRepositoryProfile, WorkRepositoryProfile.code_repository_id == CodeRepository.id)
                .where(WorkRepositoryProfile.id.in_(profile_ids))
            )
        ).scalars()
        providers = {str(provider or "").strip().lower() for provider in rows if provider}
    context: dict[str, str] = {}
    if len(providers) == 1:
        context["source_control_provider"] = next(iter(providers))
    ticket_provider = str(getattr(item, "source_type", "") or "").strip().lower()
    if ticket_provider:
        context["ticket_provider"] = ticket_provider
    return context
