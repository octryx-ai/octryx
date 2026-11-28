"""The Limits & budgets overview: sources and Workspace overrides, read-only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, BASELINE_DAILY_BUDGET_USD

from ...config import get_settings
from ...models import BudgetPolicy, Project, User
from ..budget.policy_scope import _get_limits_for_period, _load_usage_snapshot
from ..budget.project_cost_limits import COST_LIMIT_KEYS, PROJECT_RUNTIME_COST_LIMITS_KEY

GATEWAY_DAILY_KEY = "gateway_daily_usd_per_person"
RATE_LIMITS = (
    ("rate_limit_user_read_per_min", "Reads per person per minute"),
    ("rate_limit_user_write_per_min", "Writes per person per minute"),
    ("rate_limit_ip_general_per_min", "Requests per address per minute"),
    ("rate_limit_auth_per_min", "Sign-in attempts per minute"),
)


def _workspace_overrides(projects: list[tuple[str, str, Any]]) -> dict[str, list[dict[str, Any]]]:
    overrides: dict[str, list[dict[str, Any]]] = {key: [] for key in (*COST_LIMIT_KEYS, GATEWAY_DAILY_KEY)}
    for project_id, name, config in projects:
        config = config if isinstance(config, dict) else {}
        caps = config.get(PROJECT_RUNTIME_COST_LIMITS_KEY)
        for key in COST_LIMIT_KEYS:
            if isinstance(caps, dict) and caps.get(key) not in (None, ""):
                overrides[key].append({"workspace_id": project_id, "name": name, "value": str(caps[key])})
        gateway = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
        budget = gateway.get("session_budget") if isinstance(gateway, dict) else None
        if isinstance(budget, dict) and budget.get("per_user_daily_usd") not in (None, ""):
            overrides[GATEWAY_DAILY_KEY].append(
                {"workspace_id": project_id, "name": name, "value": str(budget["per_user_daily_usd"])}
            )
    return overrides


async def _budget_rows(db: AsyncSession) -> list[dict[str, Any]]:
    policies = (await db.execute(select(BudgetPolicy).order_by(BudgetPolicy.name))).scalars().all()
    names = {pid: name for pid, name in (await db.execute(select(Project.id, Project.name))).all()}
    users = {uid: name for uid, name in (await db.execute(select(User.id, User.username))).all()}
    rows = []
    for policy in policies:
        _requests, _tokens, cost_limit = _get_limits_for_period(policy)
        used = await _load_usage_snapshot(db, policy=policy) if policy.is_active else None
        rows.append({
            "id": policy.id,
            "name": policy.name,
            "scope": "workspace" if policy.project_id else "person" if policy.user_id else "other",
            "scope_label": names.get(policy.project_id) or users.get(policy.user_id) or policy.name,
            "workspace_id": policy.project_id,
            "user_id": policy.user_id,
            "period": policy.reset_period,
            "amount_usd": str(cost_limit) if cost_limit is not None else None,
            "used_usd": str(used.cost) if used is not None else None,
            "warn_at_percent": policy.warn_at_percent,
            "block_at_percent": policy.block_at_percent,
            "is_active": bool(policy.is_active),
        })
    return rows


async def limits_overview(db: AsyncSession) -> dict[str, Any]:
    projects = (
        await db.execute(select(Project.id, Project.name, Project.config).where(Project.is_active.is_(True))
                         .order_by(Project.name))
    ).all()
    settings = get_settings()
    return {
        "workspace_overrides": _workspace_overrides(list(projects)),
        "gateway_daily_baseline_usd": BASELINE_DAILY_BUDGET_USD,
        "environment_limits": [
            {"key": key, "label": label, "value": getattr(settings, key, None)} for key, label in RATE_LIMITS
        ],
        "budgets": await _budget_rows(db),
        "workspaces": [{"id": project_id, "name": name} for project_id, name, _config in projects],
        "users": [
            {"id": user_id, "name": username}
            for user_id, username in (
                await db.execute(select(User.id, User.username).where(User.is_active.is_(True)).order_by(User.username))
            ).all()
        ],
    }


__all__ = ["GATEWAY_DAILY_KEY", "limits_overview"]
