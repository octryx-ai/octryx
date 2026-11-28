"""Budget policy listing and the validated admin upsert of one policy."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ValidationError
from app.exceptions.base import NotFoundError

from ...models import BudgetPolicy
from ...models.runtime.budget import ALL_RESET_PERIODS, RESET_PERIOD_DAILY
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from .accounting import _to_decimal

_SCOPE_KEYS = (
    "user_id",
    "project_id",
    "team_id",
    "agent_chain_id",
    "flow_definition_id",
    "provider_id",
    "domain_pack_id",
)
_LIMIT_KEYS = (
    "daily_request_limit",
    "daily_token_limit",
    "daily_cost_limit",
    "weekly_request_limit",
    "weekly_token_limit",
    "weekly_cost_limit",
    "monthly_request_limit",
    "monthly_token_limit",
    "monthly_cost_limit",
)


async def list_budget_policies(
    db: AsyncSession,
    *,
    serialize_policy: Callable[[BudgetPolicy], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(BudgetPolicy).order_by(
                    BudgetPolicy.is_active.desc(), BudgetPolicy.name.asc(), BudgetPolicy.created_at.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [serialize_policy(row) for row in rows]


def _budget_policy_audit_snapshot(policy: BudgetPolicy | None) -> dict[str, Any]:
    if policy is None:
        return {}
    return {
        "id": policy.id,
        "name": policy.name,
        "user_id": policy.user_id,
        "project_id": policy.project_id,
        "team_id": policy.team_id,
        "agent_chain_id": policy.agent_chain_id,
        "flow_definition_id": policy.flow_definition_id,
        "provider_id": policy.provider_id,
        "domain_pack_id": policy.domain_pack_id,
        "reset_period": policy.reset_period,
        "daily_request_limit": policy.daily_request_limit,
        "daily_token_limit": policy.daily_token_limit,
        "daily_cost_limit": float(policy.daily_cost_limit) if policy.daily_cost_limit is not None else None,
        "weekly_request_limit": policy.weekly_request_limit,
        "weekly_token_limit": policy.weekly_token_limit,
        "weekly_cost_limit": float(policy.weekly_cost_limit) if policy.weekly_cost_limit is not None else None,
        "monthly_request_limit": policy.monthly_request_limit,
        "monthly_token_limit": policy.monthly_token_limit,
        "monthly_cost_limit": float(policy.monthly_cost_limit) if policy.monthly_cost_limit is not None else None,
        "warn_at_percent": policy.warn_at_percent,
        "block_at_percent": policy.block_at_percent,
        "is_active": policy.is_active,
    }


async def upsert_budget_policy(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    serialize_policy: Callable[[BudgetPolicy], dict[str, Any]],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    policy_id = str(payload.get("id") or "").strip()
    if policy_id:
        policy = (await db.execute(select(BudgetPolicy).where(BudgetPolicy.id == policy_id))).scalar_one_or_none()
        if not policy:
            raise NotFoundError("Budget policy", policy_id)
        before_audit = _budget_policy_audit_snapshot(policy)
    else:
        policy = BudgetPolicy(id=str(uuid.uuid4()))
        db.add(policy)
        before_audit = None

    _apply_policy_fields(policy, _validated_policy_fields(payload, policy))
    if payload.get("is_active") is not None:
        policy.is_active = bool(payload.get("is_active"))

    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.governance.budget_policy.saved",
        resource_type="budget_policy",
        resource_id=policy.id,
        project_id=policy.project_id,
        before=before_audit,
        after=_budget_policy_audit_snapshot(policy),
        details={
            "operation": "upsert_budget_policy",
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    await db.commit()
    await db.refresh(policy)
    return serialize_policy(policy)


def _validated_policy_fields(payload: dict[str, Any], policy: BudgetPolicy) -> dict[str, Any]:
    name = str(payload.get("name") or policy.name or "").strip()
    if not name:
        raise ValidationError("name is required", field="name")

    scope = {key: str(payload.get(key) or "").strip() or None for key in _SCOPE_KEYS}
    if not any(scope.values()):
        raise ValidationError("At least one scope dimension is required")

    reset_period = str(payload.get("reset_period") or RESET_PERIOD_DAILY).strip().lower()
    if reset_period not in ALL_RESET_PERIODS:
        raise ValidationError(f"reset_period must be one of {sorted(ALL_RESET_PERIODS)}", field="reset_period")

    limits = {key: payload.get(key) for key in _LIMIT_KEYS}
    if all(value in (None, "", False) for value in limits.values()):
        raise ValidationError("At least one budget limit is required")

    warn_at_percent = int(payload.get("warn_at_percent") or 80)
    block_at_percent = int(payload.get("block_at_percent") or 100)
    if not (1 <= warn_at_percent <= 1000):
        raise ValidationError("warn_at_percent must be between 1 and 1000", field="warn_at_percent")
    if not (warn_at_percent <= block_at_percent <= 1000):
        raise ValidationError("block_at_percent must be >= warn_at_percent and <= 1000", field="block_at_percent")
    return {
        "name": name,
        "scope": scope,
        "reset_period": reset_period,
        "limits": limits,
        "warn_at_percent": warn_at_percent,
        "block_at_percent": block_at_percent,
    }


def _apply_policy_fields(policy: BudgetPolicy, fields: dict[str, Any]) -> None:
    policy.name = fields["name"]
    for key in _SCOPE_KEYS:
        setattr(policy, key, fields["scope"][key])
    policy.reset_period = fields["reset_period"]
    limits = fields["limits"]
    for key in _LIMIT_KEYS:
        if key.endswith("_cost_limit"):
            setattr(policy, key, _normalize_cost_limit(limits[key]))
        else:
            setattr(policy, key, _normalize_int_limit(limits[key], key))
    policy.daily_cost_limit = _normalize_cost_limit(limits["daily_cost_limit"])
    policy.warn_at_percent = fields["warn_at_percent"]
    policy.block_at_percent = fields["block_at_percent"]


def _normalize_int_limit(raw_value: Any, field_name: str) -> int | None:
    if raw_value in (None, "", False):
        return None
    value = int(raw_value)
    if value < 0:
        raise ValidationError(f"{field_name} must be >= 0", field=field_name)
    return value


def _normalize_cost_limit(raw_value: Any) -> Decimal | None:
    if raw_value in (None, "", False):
        return None
    value = _to_decimal(raw_value)
    if value < 0:
        raise ValidationError("daily_cost_limit must be >= 0", field="daily_cost_limit")
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
