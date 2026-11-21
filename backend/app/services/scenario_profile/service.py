from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.core.context.context_planner import ContextPlan
from ...models import ScenarioProfile
from .unsupported_fields import PROMPT_MATCH_KEYS


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _profile_matches(profile: ScenarioProfile, *, context_plan: ContextPlan) -> bool:
    match_config = profile.match_config or {}
    # Scenario profiles never match prompt text: a profile carrying a prompt matcher (written around the
    # refusal in ``unsupported_fields``, e.g. directly into the table) matches no turn instead of every turn
    # of its route.
    if any(_normalize_string_list(match_config.get(key)) for key in PROMPT_MATCH_KEYS):
        return False
    route_reasons = _normalize_string_list(match_config.get("route_reasons") or match_config.get("route_reason"))
    if route_reasons and context_plan.route_reason not in route_reasons:
        return False

    required_domains = set(_normalize_string_list(match_config.get("required_domains")))
    return not (required_domains and not required_domains.issubset(set(context_plan.domains)))


def apply_scenario_profile(context_plan: ContextPlan, profile: ScenarioProfile | None) -> ContextPlan:
    """Apply a scenario profile's context sizing; it never sets the tool surface.

    ``include_tools``, ``tool_allowlist`` and ``blocked_tools`` of a profile are not read: the
    tool surface comes only from the explicit sources in ``turn_tool_surface``.
    """
    if not profile:
        return context_plan

    planner_config = profile.planner_config or {}
    execution_config = profile.execution_config or {}

    required_domains = context_plan.required_domains
    if execution_config.get("required_domains") is not None:
        required_domains = _normalize_string_list(execution_config.get("required_domains"))

    return replace(
        context_plan,
        include_system_context=bool(planner_config.get("include_system_context", context_plan.include_system_context)),
        include_skills=bool(planner_config.get("include_skills", context_plan.include_skills)),
        include_recent_history=bool(planner_config.get("include_recent_history", context_plan.include_recent_history)),
        include_summary_context=bool(
            planner_config.get("include_summary_context", context_plan.include_summary_context)
        ),
        recent_history_limit=int(planner_config.get("recent_history_limit", context_plan.recent_history_limit)),
        system_prompt_variant=str(planner_config.get("system_prompt_variant", context_plan.system_prompt_variant)),
        token_budget=int(planner_config.get("token_budget", context_plan.token_budget)),
        required_domains=required_domains,
        enforce_domain_coverage=bool(
            execution_config.get("enforce_domain_coverage", context_plan.enforce_domain_coverage)
        ),
        scenario_profile_id=profile.id,
        scenario_profile_name=profile.name,
    )


async def resolve_scenario_profile(
    db: AsyncSession,
    *,
    owner_id: str,
    project_id: str | None,
    context_plan: ContextPlan,
) -> ScenarioProfile | None:
    stmt = (
        select(ScenarioProfile)
        .where(
            ScenarioProfile.owner_id == owner_id,
            ScenarioProfile.is_active == True,  # noqa: E712
            or_(ScenarioProfile.project_id == project_id, ScenarioProfile.project_id.is_(None)),
        )
        .order_by(
            ScenarioProfile.priority.desc(),
            case((ScenarioProfile.project_id == project_id, 1), else_=0).desc(),
            ScenarioProfile.updated_at.desc(),
        )
    )
    profiles = (await db.execute(stmt)).scalars().all()
    for profile in profiles:
        if _profile_matches(profile, context_plan=context_plan):
            return profile
    return None
