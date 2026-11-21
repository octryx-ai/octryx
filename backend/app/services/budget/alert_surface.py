"""The admin budget alert surface: recent alerts and the policies blocking right now."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetAlert, BudgetPolicy
from .accounting import _to_decimal
from .policy_scope import _get_limits_for_period, _load_usage_snapshot


def _serialize_budget_value(metric_name: str, value: Decimal) -> int | float:
    normalized = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if metric_name in {"requests", "tokens"}:
        return int(normalized)
    return float(normalized)


def _serialize_budget_alert_row(
    *,
    alert: BudgetAlert,
    policy_name: str | None = None,
) -> dict[str, Any]:
    details = dict(alert.details or {})
    resolved_policy_name = str(policy_name or details.get("policy_name") or "").strip()
    if resolved_policy_name:
        details["policy_name"] = resolved_policy_name
    return {
        "id": alert.id,
        "policyId": alert.policy_id,
        "policyName": resolved_policy_name,
        "userId": alert.user_id or "",
        "projectId": alert.project_id or "",
        "sessionId": alert.session_id or "",
        "metricName": alert.metric_name,
        "thresholdLevel": alert.threshold_level,
        "currentValue": _serialize_budget_value(alert.metric_name, _to_decimal(alert.current_value)),
        "limitValue": _serialize_budget_value(alert.metric_name, _to_decimal(alert.limit_value)),
        "percentUsed": int(alert.percent_used or 0),
        "message": alert.message or "",
        "details": details,
        "createdAt": alert.created_at.isoformat() if alert.created_at else None,
    }


def _build_active_block_entry(
    *,
    policy: BudgetPolicy,
    metric_name: str,
    current_value: Decimal,
    limit_value: Decimal,
    percent_used: int,
) -> dict[str, Any]:
    return {
        "policyId": policy.id,
        "policyName": policy.name,
        "userId": policy.user_id or "",
        "projectId": policy.project_id or "",
        "metricName": metric_name,
        "currentValue": _serialize_budget_value(metric_name, current_value),
        "limitValue": _serialize_budget_value(metric_name, limit_value),
        "percentUsed": percent_used,
        "warnAtPercent": int(policy.warn_at_percent or 80),
        "blockAtPercent": int(policy.block_at_percent or 100),
    }


async def list_budget_alert_surface(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit or 100), 500))
    alert_rows = (
        await db.execute(
            select(BudgetAlert, BudgetPolicy.name)
            .join(BudgetPolicy, BudgetPolicy.id == BudgetAlert.policy_id)
            .order_by(BudgetAlert.created_at.desc(), BudgetAlert.id.desc())
            .limit(bounded_limit)
        )
    ).all()
    alerts = [_serialize_budget_alert_row(alert=alert, policy_name=policy_name) for alert, policy_name in alert_rows]

    active_blocks: list[dict[str, Any]] = []
    policies = (
        (
            await db.execute(
                select(BudgetPolicy)
                .where(BudgetPolicy.is_active)
                .order_by(BudgetPolicy.name.asc(), BudgetPolicy.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for policy in policies:
        usage = await _load_usage_snapshot(db, policy=policy)
        req_limit, tok_limit, cost_limit = _get_limits_for_period(policy)
        checks = [
            ("requests", _to_decimal(usage.requests), _to_decimal(req_limit)),
            ("tokens", _to_decimal(usage.tokens), _to_decimal(tok_limit)),
            ("cost", usage.cost, _to_decimal(cost_limit)),
        ]
        for metric_name, current_value, limit_value in checks:
            if limit_value <= 0:
                continue
            percent_used = int((current_value / limit_value * 100).to_integral_value(rounding=ROUND_HALF_UP))
            if percent_used < int(policy.block_at_percent or 100):
                continue
            active_blocks.append(
                _build_active_block_entry(
                    policy=policy,
                    metric_name=metric_name,
                    current_value=current_value,
                    limit_value=limit_value,
                    percent_used=percent_used,
                )
            )

    return {
        "alerts": alerts,
        "activeBlocks": active_blocks,
        "summary": {
            "alertCount": len(alerts),
            "activeBlockCount": len(active_blocks),
        },
    }
