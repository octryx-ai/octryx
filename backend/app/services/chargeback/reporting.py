from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CostAllocationRule, MonthlyCostReport, Project, Session, UsageEvent
from ...time_utils import utc_now
from .periods import parse_report_period
from .serialization import serialize_monthly_cost_report


def _empty_group_bundle() -> dict[str, Any]:
    return {"total_cost": Decimal("0"), "usage_events": 0, "cost_centers": defaultdict(float)}


def _normalize_grouped_cost_projects(
    grouped_costs: dict[tuple[str | None, str | None], dict[str, Any]],
    *,
    valid_project_ids: set[str],
) -> dict[tuple[str | None, str | None], dict[str, Any]]:
    normalized: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for (project_id, provider_id), bundle in grouped_costs.items():
        normalized_project_id = project_id if (project_id is None or project_id in valid_project_ids) else None
        key = (normalized_project_id, provider_id)
        target = normalized.setdefault(key, _empty_group_bundle())
        target["total_cost"] += Decimal(str(bundle["total_cost"]))
        target["usage_events"] += bundle["usage_events"]
    return normalized


def _report_window(start_date: Any, end_date: Any) -> tuple[Any, Any]:
    start_dt = utc_now().replace(
        year=start_date.year,
        month=start_date.month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if end_date.month == 1 and start_date.month == 12:
        end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
    else:
        end_dt = start_dt.replace(month=end_date.month, year=end_date.year)
    return start_dt, end_dt


async def _grouped_usage_costs(
    db: AsyncSession, *, start_dt: Any, end_dt: Any
) -> dict[tuple[str | None, str | None], dict[str, Any]]:
    usage_rows = (
        await db.execute(
            select(UsageEvent, Session.project_id)
            .join(Session, Session.id == UsageEvent.session_id)
            .where(
                UsageEvent.created_at >= start_dt,
                UsageEvent.created_at < end_dt,
            )
        )
    ).all()

    grouped_costs: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for usage_event, session_project_id in usage_rows:
        key = (session_project_id, str(usage_event.provider or "").strip() or None)
        bundle = grouped_costs.setdefault(key, _empty_group_bundle())
        bundle["total_cost"] += Decimal(str(float(usage_event.cost or 0.0)))
        bundle["usage_events"] += 1
    return grouped_costs


async def _rules_by_project(
    db: AsyncSession, *, project_ids: set[str], start_date: Any
) -> dict[str, list[CostAllocationRule]]:
    rule_rows: list[CostAllocationRule] = []
    if project_ids:
        rule_rows = (
            (
                await db.execute(
                    select(CostAllocationRule)
                    .where(CostAllocationRule.project_id.in_(project_ids))
                    .where(CostAllocationRule.valid_from <= start_date)
                    .order_by(CostAllocationRule.valid_from.desc(), CostAllocationRule.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    rules_by_project: dict[str, list[CostAllocationRule]] = defaultdict(list)
    for row in rule_rows:
        rules_by_project[row.project_id].append(row)
    return rules_by_project


def _allocations(total_cost: float, applicable_rules: list[CostAllocationRule]) -> list[dict[str, Any]]:
    allocations: list[dict[str, Any]] = []
    if applicable_rules:
        for rule in applicable_rules:
            allocations.append(
                {
                    "cost_center": rule.cost_center,
                    "percentage": float(rule.percentage or 0),
                    "allocated_cost": round(total_cost * (float(rule.percentage or 0) / 100.0), 6),
                }
            )
    else:
        allocations.append(
            {
                "cost_center": "unallocated",
                "percentage": 100.0,
                "allocated_cost": round(total_cost, 6),
            }
        )
    return allocations


async def generate_monthly_cost_report(db: AsyncSession, *, period: str) -> list[dict[str, Any]]:
    normalized_period, start_date, end_date = parse_report_period(period)
    start_dt, end_dt = _report_window(start_date, end_date)
    grouped_costs = await _grouped_usage_costs(db, start_dt=start_dt, end_dt=end_dt)

    project_ids = {project_id for project_id, _provider in grouped_costs.keys() if project_id}
    if project_ids:
        valid_project_ids = set(
            (await db.execute(select(Project.id).where(Project.id.in_(project_ids)))).scalars().all()
        )
        grouped_costs = _normalize_grouped_cost_projects(grouped_costs, valid_project_ids=valid_project_ids)
        project_ids = {project_id for project_id, _provider in grouped_costs.keys() if project_id}

    rules_by_project = await _rules_by_project(db, project_ids=project_ids, start_date=start_date)

    await db.execute(delete(MonthlyCostReport).where(MonthlyCostReport.period == normalized_period))
    await db.flush()

    reports: list[MonthlyCostReport] = []
    for (project_id, provider_id), bundle in sorted(
        grouped_costs.items(),
        key=lambda item: (item[0][0] or "", item[0][1] or ""),
    ):
        total_cost = float(bundle["total_cost"])
        allocations = _allocations(total_cost, rules_by_project.get(project_id or "", []))

        report_row = MonthlyCostReport(
            id=str(uuid.uuid4()),
            period=normalized_period,
            project_id=project_id,
            provider_id=provider_id,
            total_cost=round(total_cost, 6),
        )
        report_row.report = {
            "usage_event_count": bundle["usage_events"],
            "cost_centers": allocations,
        }
        db.add(report_row)
        reports.append(report_row)

    await db.commit()
    return [serialize_monthly_cost_report(row) for row in reports]


async def list_monthly_cost_reports(db: AsyncSession, *, period: str) -> list[dict[str, Any]]:
    normalized_period, _start_date, _end_date = parse_report_period(period)
    rows = (
        (
            await db.execute(
                select(MonthlyCostReport)
                .where(MonthlyCostReport.period == normalized_period)
                .order_by(MonthlyCostReport.project_id.asc(), MonthlyCostReport.provider_id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return await generate_monthly_cost_report(db, period=normalized_period)
    return [serialize_monthly_cost_report(row) for row in rows]
