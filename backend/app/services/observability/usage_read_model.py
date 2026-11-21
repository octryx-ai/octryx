"""Observability → Usage & costs (O3): one cost source, ``usage_events``, over a chosen window.

Every figure is a SQL aggregate over ``usage_events`` in the window (7 days, 30 days, or this month, UTC):
spend counts priced events only; **priced coverage** is the share of platform-billed tokens that carry a price
(seat and device usage is not billed to the platform and is left out); tokens include cache reads and writes.
Budgets are shown read-only: the caps are declared in Runtime → Limits & budgets.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetPolicy, Project, Session, TurnTraceSummary, UsageEvent, User
from ...time_utils import ensure_utc, utc_now
from ..budget.agent_cost_limits import agent_request_cost_limit, agent_session_cost_limit
from ..budget.unpriced_guard import unpriced_model_policy
from .cost_states import COST_NOT_BILLED, COST_PRICED, COST_UNPRICED, cost_state_expression

WINDOWS = ("7d", "30d", "month")
DEFAULT_WINDOW = "month"
TOP_USERS = 5


def window_bounds(window: str, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or utc_now()
    if window == "7d":
        return (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0), now
    if window == "30d":
        return (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0), now
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now


def _tokens():
    return (
        func.coalesce(UsageEvent.tokens_in, 0) + func.coalesce(UsageEvent.tokens_out, 0)
        + func.coalesce(UsageEvent.cache_read_tokens, 0) + func.coalesce(UsageEvent.cache_creation_tokens, 0)
    )


def _money(value: Any) -> float:
    return round(float(value or 0), 6)


def _iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


async def usage_overview(db: AsyncSession, *, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
    window = window if window in WINDOWS else DEFAULT_WINDOW
    start, end = window_bounds(window)
    in_window = (UsageEvent.created_at >= start, UsageEvent.created_at < end)
    state = cost_state_expression()

    by_state = {
        row_state: {"tokens": int(tokens or 0), "cost": _money(cost)}
        for row_state, tokens, cost in (await db.execute(
            select(state, func.sum(_tokens()), func.sum(UsageEvent.cost)).where(*in_window).group_by(state)
        )).all()
    }
    priced = by_state.get(COST_PRICED, {"tokens": 0, "cost": 0.0})
    unpriced = by_state.get(COST_UNPRICED, {"tokens": 0, "cost": 0.0})
    billed_tokens = priced["tokens"] + unpriced["tokens"]
    totals = (await db.execute(
        select(
            func.coalesce(func.sum(_tokens()), 0),
            func.coalesce(func.sum(func.coalesce(UsageEvent.cache_read_tokens, 0)
                                   + func.coalesce(UsageEvent.cache_creation_tokens, 0)), 0),
            func.count(func.distinct(UsageEvent.user_id)),
        ).where(*in_window)
    )).one()
    return {
        "window": window,
        "since": _iso(start),
        "until": _iso(end),
        "tiles": {
            "spend": priced["cost"],
            "priced_coverage": round(priced["tokens"] / billed_tokens, 4) if billed_tokens else None,
            "unpriced_tokens": unpriced["tokens"],
            "platform_billed_tokens": billed_tokens,
            "tokens": int(totals[0] or 0),
            "cache_tokens": int(totals[1] or 0),
            "active_users": int(totals[2] or 0),
        },
        "unpriced_policy": await unpriced_model_policy(db),
        "daily": await _daily(db, start, end),
        "by_model": await _by_model(db, in_window),
        "by_workspace": await _by_workspace(db, start, end),
        "by_user": await _by_user(db, start, end),
        "budgets": await _budgets(db, start, end),
    }


async def _daily(db: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # date() returns the UTC day on both PostgreSQL and SQLite; compared as ISO text.
    day = func.date(UsageEvent.created_at, type_=String)
    state = cost_state_expression()
    rows = (await db.execute(
        select(day, func.sum(UsageEvent.cost)).where(
            UsageEvent.created_at >= start, UsageEvent.created_at < end, state == COST_PRICED
        ).group_by(day)
    )).all()
    spent = {str(row_day): _money(cost) for row_day, cost in rows}
    days, cursor = [], start.date()
    while cursor <= (end - timedelta(microseconds=1)).date():
        days.append({"day": cursor.isoformat(), "spend": spent.get(cursor.isoformat(), 0.0)})
        cursor += timedelta(days=1)
    return days


async def _by_model(db: AsyncSession, in_window: tuple) -> list[dict[str, Any]]:
    state = cost_state_expression()
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for provider, model, row_state, tokens, cost in (await db.execute(
        select(UsageEvent.provider, UsageEvent.model, state, func.sum(_tokens()), func.sum(UsageEvent.cost))
        .where(*in_window).group_by(UsageEvent.provider, UsageEvent.model, state)
    )).all():
        entry = models.setdefault((provider or "", model or ""), {
            "provider": provider or "", "model": model or "", "tokens": 0, "unpriced_tokens": 0, "cost": 0.0,
            "states": set(),
        })
        entry["tokens"] += int(tokens or 0)
        entry["cost"] = _money(entry["cost"] + float(cost or 0))
        entry["states"].add(row_state)
        if row_state == COST_UNPRICED:
            entry["unpriced_tokens"] += int(tokens or 0)
    result = []
    for entry in models.values():
        states = entry.pop("states")
        entry["pricing"] = (COST_UNPRICED if COST_UNPRICED in states
                            else COST_PRICED if COST_PRICED in states else COST_NOT_BILLED)
        result.append(entry)
    return sorted(result, key=lambda item: item["tokens"], reverse=True)


async def _runs_per(db: AsyncSession, column, start: datetime, end: datetime) -> dict[str, int]:
    return {
        str(key): int(count)
        for key, count in (await db.execute(
            select(column, func.count(func.distinct(TurnTraceSummary.run_key)))
            .join(Session, Session.id == TurnTraceSummary.session_id)
            .where(TurnTraceSummary.created_at >= start, TurnTraceSummary.created_at < end)
            .group_by(column)
        )).all()
    }


async def _by_workspace(db: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(Session.project_id, Project.name, func.sum(UsageEvent.cost))
        .join(Session, Session.id == UsageEvent.session_id)
        .outerjoin(Project, Project.id == Session.project_id)
        .where(UsageEvent.created_at >= start, UsageEvent.created_at < end)
        .group_by(Session.project_id, Project.name)
    )).all()
    runs = await _runs_per(db, Session.project_id, start, end)
    budgets = await _monthly_budgets(db)
    return sorted(
        ({"workspace_id": project_id, "workspace_name": name, "runs": runs.get(str(project_id), 0),
          "cost": _money(cost), "budget": budgets.get(project_id)} for project_id, name, cost in rows),
        key=lambda item: item["cost"], reverse=True,
    )


async def _by_user(db: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(UsageEvent.user_id, User.username, User.display_name, func.sum(UsageEvent.cost))
        .outerjoin(User, User.id == UsageEvent.user_id)
        .where(UsageEvent.created_at >= start, UsageEvent.created_at < end)
        .group_by(UsageEvent.user_id, User.username, User.display_name)
        .order_by(func.sum(UsageEvent.cost).desc())
        .limit(TOP_USERS)
    )).all()
    runs = await _runs_per(db, Session.user_id, start, end)
    return [{"user_id": user_id, "user_name": display or username or user_id, "runs": runs.get(str(user_id), 0),
             "cost": _money(cost)} for user_id, username, display, cost in rows]


async def _monthly_budgets(db: AsyncSession) -> dict[str | None, dict[str, Any]]:
    """Active Workspace budget policies with a monthly cost limit (declared in Runtime → Limits & budgets)."""
    month_start, now = window_bounds("month")
    result: dict[str | None, dict[str, Any]] = {}
    for policy in (await db.execute(select(BudgetPolicy).where(
        BudgetPolicy.is_active.is_(True), BudgetPolicy.monthly_cost_limit.is_not(None),
        BudgetPolicy.project_id.is_not(None),
    ))).scalars():
        used = (await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0)).join(Session, Session.id == UsageEvent.session_id)
            .where(Session.project_id == policy.project_id, UsageEvent.created_at >= month_start)
        )).scalar()
        limit = float(policy.monthly_cost_limit or 0)
        result[policy.project_id] = {"name": policy.name, "limit": limit, "used": _money(used),
                                     "percent": round(float(used or 0) / limit * 100) if limit else None}
    return result


async def _budgets(db: AsyncSession, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The platform caps with the highest cost they met in the window (read-only)."""
    request_cap = (await agent_request_cost_limit(db, project_id=None)).value
    session_cap = (await agent_session_cost_limit(db, project_id=None)).value
    max_request = (await db.execute(select(func.max(UsageEvent.cost)).where(
        UsageEvent.created_at >= start, UsageEvent.created_at < end))).scalar()
    per_session = (select(func.sum(UsageEvent.cost).label("cost")).where(
        UsageEvent.created_at >= start, UsageEvent.created_at < end).group_by(UsageEvent.session_id).subquery())
    max_session = (await db.execute(select(func.max(per_session.c.cost)))).scalar()

    def row(label: str, cap: Decimal, used: Any) -> dict[str, Any]:
        cap_value = float(cap)
        used_value = _money(used)
        return {"limit": label, "scope": "platform", "cap": cap_value or None, "used": used_value,
                "percent": round(used_value / cap_value * 100) if cap_value else None}

    rows = [row("Per request", request_cap, max_request), row("Per session", session_cap, max_session)]
    for workspace_id, budget in (await _monthly_budgets(db)).items():
        rows.append({"limit": "Monthly", "scope": budget["name"], "workspace_id": workspace_id, "cap": budget["limit"],
                     "used": budget["used"], "percent": budget["percent"]})
    return rows


__all__ = ["DEFAULT_WINDOW", "WINDOWS", "usage_overview", "window_bounds"]
