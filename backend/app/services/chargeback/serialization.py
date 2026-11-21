from __future__ import annotations

from typing import Any

from ...models import CostAllocationRule, MonthlyCostReport


def serialize_cost_allocation_rule(row: CostAllocationRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "cost_center": row.cost_center,
        "percentage": float(row.percentage or 0),
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_monthly_cost_report(row: MonthlyCostReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "period": row.period,
        "project_id": row.project_id,
        "provider_id": row.provider_id,
        "total_cost": float(row.total_cost or 0),
        "report": row.report,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
