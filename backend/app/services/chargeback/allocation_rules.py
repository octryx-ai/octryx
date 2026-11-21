from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CostAllocationRule, Project
from .serialization import serialize_cost_allocation_rule


async def list_cost_allocation_rules(db: AsyncSession, *, project_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(CostAllocationRule).order_by(
        CostAllocationRule.valid_from.desc(),
        CostAllocationRule.created_at.desc(),
    )
    if project_id:
        stmt = stmt.where(CostAllocationRule.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_cost_allocation_rule(row) for row in rows]


def _validated_rule_fields(project_id: str, cost_center: str, percentage: float) -> tuple[str, str, float]:
    normalized_project_id = str(project_id or "").strip()
    normalized_center = str(cost_center or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if not normalized_center:
        raise HTTPException(status_code=400, detail="cost_center is required")

    value = float(percentage)
    if value <= 0 or value > 100:
        raise HTTPException(status_code=400, detail="percentage must be between 0 and 100")
    return normalized_project_id, normalized_center, value


async def upsert_cost_allocation_rule(
    db: AsyncSession,
    *,
    rule_id: str | None,
    project_id: str,
    cost_center: str,
    percentage: float,
    valid_from: date,
) -> dict[str, Any]:
    normalized_project_id, normalized_center, value = _validated_rule_fields(project_id, cost_center, percentage)

    project = await db.get(Project, normalized_project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    existing_rules = (
        (
            await db.execute(
                select(CostAllocationRule).where(
                    CostAllocationRule.project_id == normalized_project_id,
                    CostAllocationRule.valid_from == valid_from,
                )
            )
        )
        .scalars()
        .all()
    )
    current_total = sum(
        float(existing.percentage or 0) for existing in existing_rules if str(existing.id) != str(rule_id or "")
    )
    if current_total + value > 100.000001:
        raise HTTPException(status_code=400, detail="Total allocation percentage for this project/date exceeds 100")

    row = await db.get(CostAllocationRule, rule_id) if rule_id else None
    if row is None:
        row = CostAllocationRule(
            id=str(uuid.uuid4()),
            project_id=normalized_project_id,
            cost_center=normalized_center,
            percentage=value,
            valid_from=valid_from,
        )
        db.add(row)
    else:
        row.project_id = normalized_project_id
        row.cost_center = normalized_center
        row.percentage = value
        row.valid_from = valid_from

    await db.commit()
    await db.refresh(row)
    return serialize_cost_allocation_rule(row)


async def delete_cost_allocation_rule(db: AsyncSession, *, rule_id: str) -> dict[str, Any]:
    row = await db.get(CostAllocationRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Cost allocation rule not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": rule_id}
