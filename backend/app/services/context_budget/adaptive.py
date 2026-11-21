"""Adaptive per-turn context budget derived from the matching budget profile."""

from __future__ import annotations

import copy
import re
from dataclasses import is_dataclass, replace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.context.context_planner import ContextPlan
from ...models import ContextBudgetProfile, Session, UsageEvent
from .profiles import ensure_default_context_budget_profiles


def _replace_context_plan(context_plan: ContextPlan, **changes: Any) -> ContextPlan:
    if is_dataclass(context_plan):
        return replace(context_plan, **changes)
    cloned = copy.copy(context_plan)
    for key, value in changes.items():
        setattr(cloned, key, value)
    return cloned



def _build_profile_haystack(
    *,
    context_plan: ContextPlan,
    agent_type: str,
    capability_type: str,
    has_parent_context: bool,
    sub_agent_depth: int,
) -> str:
    """The explicit tokens a budget profile's ``trigger_pattern`` matches; never the prompt text."""
    flags: list[str] = []
    if has_parent_context or int(sub_agent_depth or 0) > 0:
        flags.append("subagent")
    return " ".join(
        part
        for part in [
            context_plan.route_reason,
            context_plan.tier,
            agent_type,
            capability_type,
            " ".join(flags),
        ]
        if part
    )


async def _resolve_matching_profile(
    db: AsyncSession,
    *,
    context_plan: ContextPlan,
    agent_type: str,
    capability_type: str,
    has_parent_context: bool,
    sub_agent_depth: int,
) -> ContextBudgetProfile | None:
    await ensure_default_context_budget_profiles(db)
    haystack = _build_profile_haystack(
        context_plan=context_plan,
        agent_type=agent_type,
        capability_type=capability_type,
        has_parent_context=has_parent_context,
        sub_agent_depth=sub_agent_depth,
    )
    rows = (
        (
            await db.execute(
                select(ContextBudgetProfile)
                .where(ContextBudgetProfile.is_active == True)  # noqa: E712
                .order_by(ContextBudgetProfile.priority.desc(), ContextBudgetProfile.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        try:
            if re.search(str(row.trigger_pattern or "").strip(), haystack, re.IGNORECASE):
                return row
        except re.error:
            continue
    return rows[-1] if rows else None


async def estimate_similar_session_avg_tokens(
    db: AsyncSession,
    *,
    project_id: str | None,
    agent_type: str,
    route_reason: str,
    has_parent_context: bool,
) -> int:
    session_stmt = select(Session.id).where(Session.agent_type == agent_type)
    if project_id:
        session_stmt = session_stmt.where(Session.project_id == project_id)
    if has_parent_context or route_reason == "change_or_continuation":
        session_stmt = session_stmt.where(Session.parent_session_id.is_not(None))
    session_ids = (await db.execute(session_stmt.order_by(Session.started_at.desc()).limit(40))).scalars().all()
    if not session_ids:
        return 0
    token_rows = (
        await db.execute(
            select(
                UsageEvent.session_id,
                (func.sum(UsageEvent.tokens_in) + func.sum(UsageEvent.tokens_out)).label("total_tokens"),
            )
            .where(UsageEvent.session_id.in_(session_ids))
            .group_by(UsageEvent.session_id)
        )
    ).all()
    totals = [int(row.total_tokens or 0) for row in token_rows if int(row.total_tokens or 0) > 0]
    if not totals:
        return 0
    return int(sum(totals) / len(totals))



def _budget_breakdown(
    profile: ContextBudgetProfile,
    *,
    context_plan: ContextPlan,
    history_count: int,
    entity_count: int,
    tool_count: int,
    similar_session_avg_tokens: int,
    scenario_budget_override: bool,
) -> tuple[int, dict[str, Any]]:
    tool_units = max(0, min(int(tool_count or 0), 8))
    history_units = max(0, min(int(history_count or 0), max(0, int(context_plan.recent_history_limit or 0))))
    entity_units = max(0, min(int(entity_count or 0), 8))
    base_budget = int(profile.base_budget or 0)
    tool_budget_total = tool_units * int(profile.tool_budget or 0)
    history_budget_total = history_units * int(profile.history_budget or 0)
    entity_budget_total = entity_units * int(profile.entity_budget or 0)
    computed_budget = base_budget + tool_budget_total + history_budget_total + entity_budget_total
    historical_floor = int(similar_session_avg_tokens * 1.1) if similar_session_avg_tokens > 0 else 0
    historical_boost = max(0, historical_floor - computed_budget)
    max_budget = max(
        base_budget,
        base_budget
        + int(profile.tool_budget or 0) * 8
        + int(profile.history_budget or 0) * 12
        + int(profile.entity_budget or 0) * 8
        # No turn injects memory (the governed lobe is recalled by tool), so a profile's
        # ``memory_budget`` only keeps its original share of the cap headroom.
        + int(profile.memory_budget or 0) * 8,
    )
    adaptive_budget = min(max(computed_budget, historical_floor or computed_budget), max_budget)
    final_budget = int(context_plan.token_budget) if scenario_budget_override else adaptive_budget
    return final_budget, {
        "base_budget": base_budget,
        "tool_units": tool_units,
        "tool_budget_total": tool_budget_total,
        "history_units": history_units,
        "history_budget_total": history_budget_total,
        "entity_units": entity_units,
        "entity_budget_total": entity_budget_total,
        "similar_session_avg_tokens": max(0, similar_session_avg_tokens),
        "historical_boost": historical_boost,
        "computed_budget": computed_budget,
        "final_budget": max(0, final_budget),
    }


async def apply_adaptive_context_budget(
    db: AsyncSession,
    *,
    context_plan: ContextPlan,
    project_id: str | None,
    agent_type: str,
    capability_type: str,
    history_count: int,
    entity_count: int,
    tool_count: int,
    has_parent_context: bool,
    sub_agent_depth: int,
    scenario_budget_override: bool = False,
) -> ContextPlan:
    profile = await _resolve_matching_profile(
        db,
        context_plan=context_plan,
        agent_type=agent_type,
        capability_type=capability_type,
        has_parent_context=has_parent_context,
        sub_agent_depth=sub_agent_depth,
    )
    if profile is None:
        return context_plan

    similar_session_avg_tokens = await estimate_similar_session_avg_tokens(
        db,
        project_id=project_id,
        agent_type=agent_type,
        route_reason=context_plan.route_reason,
        has_parent_context=has_parent_context,
    )
    final_budget, breakdown = _budget_breakdown(
        profile,
        context_plan=context_plan,
        history_count=history_count,
        entity_count=entity_count,
        tool_count=tool_count,
        similar_session_avg_tokens=similar_session_avg_tokens,
        scenario_budget_override=scenario_budget_override,
    )
    return _replace_context_plan(
        context_plan,
        token_budget=max(0, final_budget),
        budget_profile_id=str(profile.id or ""),
        budget_profile_name=str(profile.name or ""),
        similar_session_avg_tokens=max(0, similar_session_avg_tokens),
        budget_breakdown=breakdown,
    )
