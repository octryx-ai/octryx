"""Budget enforcement before a model call: default agent cost guards and the applicable policies."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.tool import BudgetLimitExceededError

from ...models import BudgetAlert, BudgetPolicy
from .accounting import _ZERO, _to_decimal
from .agent_cost_limits import agent_request_cost_limit, agent_session_cost_limit
from .cost_attribution import estimate_prompt_tokens, estimate_runtime_cost
from .policy_scope import (
    _get_limits_for_period,
    _list_applicable_policies,
    _load_session_usage_cost,
    _load_usage_snapshot,
    _policy_window,
)
from .unpriced_guard import enforce_priced_models_under_cap


async def effective_agent_session_cost_limit(db: AsyncSession, *, project_id: str | None) -> Decimal:
    return (await agent_session_cost_limit(db, project_id=project_id)).value


async def _enforce_default_agent_cost_limits(
    db: AsyncSession,
    *,
    session_id: str,
    project_id: str | None,
    estimated_request_cost: Decimal,
) -> None:
    request_limit = (await agent_request_cost_limit(db, project_id=project_id)).value
    if request_limit > 0 and estimated_request_cost >= request_limit:
        raise BudgetLimitExceededError(
            policy_name="Default agent request cost guard",
            metric_name="cost",
            projected_value=estimated_request_cost,
            limit_value=request_limit,
            threshold_level="block",
        )

    session_limit = await effective_agent_session_cost_limit(db, project_id=project_id)
    if session_limit <= 0:
        return
    current_cost = await _load_session_usage_cost(db, session_id=session_id)
    projected_cost = current_cost + estimated_request_cost
    if projected_cost >= session_limit:
        raise BudgetLimitExceededError(
            policy_name="Default agent session cost guard",
            metric_name="cost",
            projected_value=projected_cost,
            limit_value=session_limit,
            threshold_level="block",
        )


async def _ensure_budget_alert(
    db: AsyncSession,
    *,
    policy: BudgetPolicy,
    session_id: str | None,
    metric_name: str,
    threshold_level: str,
    current_value: Decimal,
    limit_value: Decimal,
    percent_used: int,
    message: str,
) -> None:
    start, end = _policy_window(policy)
    existing = (
        await db.execute(
            select(BudgetAlert).where(
                BudgetAlert.policy_id == policy.id,
                BudgetAlert.metric_name == metric_name,
                BudgetAlert.threshold_level == threshold_level,
                BudgetAlert.created_at >= start,
                BudgetAlert.created_at < end,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        BudgetAlert(
            id=str(uuid.uuid4()),
            policy_id=policy.id,
            user_id=policy.user_id,
            project_id=policy.project_id,
            session_id=session_id,
            metric_name=metric_name,
            threshold_level=threshold_level,
            current_value=current_value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            limit_value=limit_value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            percent_used=percent_used,
            details={
                "policy_name": policy.name,
                "warn_at_percent": int(policy.warn_at_percent or 80),
                "block_at_percent": int(policy.block_at_percent or 100),
            },
            message=message,
        )
    )


async def enforce_budget_limits(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    project_id: str | None,
    runtimes: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_completion_tokens: int,
    approx_chars_per_token: int,
    agent_chain_id: str | None = None,
    flow_definition_id: str | None = None,
    provider_id: str | None = None,
) -> None:
    applicable_policies = await _list_applicable_policies(
        db,
        user_id=user_id,
        project_id=project_id,
        agent_chain_id=agent_chain_id,
        flow_definition_id=flow_definition_id,
        provider_id=provider_id,
    )

    await enforce_priced_models_under_cap(db, runtimes=runtimes, project_id=project_id, policies=applicable_policies)
    estimated_prompt_tokens = estimate_prompt_tokens(messages, approx_chars_per_token=approx_chars_per_token)
    estimated_completion_tokens = max(0, int(max_completion_tokens or 0))
    estimated_tokens = estimated_prompt_tokens + estimated_completion_tokens
    estimated_cost = await _estimated_request_cost(
        db, runtimes, prompt_tokens=estimated_prompt_tokens, completion_tokens=estimated_completion_tokens
    )
    await _enforce_default_agent_cost_limits(
        db,
        session_id=session_id,
        project_id=project_id,
        estimated_request_cost=estimated_cost,
    )
    if not applicable_policies:
        return

    for policy in applicable_policies:
        await _enforce_policy(
            db, policy, session_id=session_id, estimated_tokens=estimated_tokens, estimated_cost=estimated_cost
        )
    await db.commit()


async def _estimated_request_cost(
    db: AsyncSession, runtimes: list[dict[str, Any]], *, prompt_tokens: int, completion_tokens: int
) -> Decimal:
    runtime_costs = [
        await estimate_runtime_cost(
            db,
            provider_name=str(runtime.get("provider_name") or ""),
            model_id=str(runtime.get("model") or ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        for runtime in (runtimes or [])
        if str(runtime.get("provider_name") or "").strip() and str(runtime.get("model") or "").strip()
    ]
    return max(runtime_costs) if runtime_costs else _ZERO


async def _enforce_policy(
    db: AsyncSession,
    policy: BudgetPolicy,
    *,
    session_id: str,
    estimated_tokens: int,
    estimated_cost: Decimal,
) -> None:
    usage = await _load_usage_snapshot(db, policy=policy)
    req_limit, tok_limit, cost_limit = _get_limits_for_period(policy)
    checks = [
        ("requests", _to_decimal(usage.requests + 1), _to_decimal(req_limit)),
        ("tokens", _to_decimal(usage.tokens + estimated_tokens), _to_decimal(tok_limit)),
        ("cost", usage.cost + estimated_cost, _to_decimal(cost_limit)),
    ]
    for metric_name, projected_value, limit_value in checks:
        if limit_value <= 0:
            continue
        percent_used = int((projected_value / limit_value * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if percent_used >= int(policy.block_at_percent or 100):
            message = (
                f"Budget policy '{policy.name}' blocks this request for {metric_name} "
                f"({percent_used}% of limit reached)."
            )
            await _ensure_budget_alert(
                db,
                policy=policy,
                session_id=session_id,
                metric_name=metric_name,
                threshold_level="block",
                current_value=projected_value,
                limit_value=limit_value,
                percent_used=percent_used,
                message=message,
            )
            await db.commit()
            raise BudgetLimitExceededError(
                policy_name=policy.name,
                metric_name=metric_name,
                projected_value=projected_value,
                limit_value=limit_value,
                threshold_level="block",
            )
        if percent_used >= int(policy.warn_at_percent or 80):
            message = (
                f"Budget policy '{policy.name}' reached warning level for {metric_name} ({percent_used}% of limit)."
            )
            await _ensure_budget_alert(
                db,
                policy=policy,
                session_id=session_id,
                metric_name=metric_name,
                threshold_level="warning",
                current_value=projected_value,
                limit_value=limit_value,
                percent_used=percent_used,
                message=message,
            )
