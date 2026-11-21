"""Context planning: tier, context sections and size budget of a turn from explicit inputs.

Tier routing is decided by the explicit policy table in
``app.services.context_routing_policy``. The planner reads only explicit inputs: the agent
mode's capability, the agent blueprint, the session's task/parent context, the Workspace and
the conversation's size. It never reads the prompt text, so two wordings of the same
turn get the same plan.

The planner does not decide the tool surface. ``turn_tool_surface.resolve_turn_tool_surface``
sets ``include_tools``, ``tool_allowlist`` and ``tool_surface_source`` from the explicit
sources (selected definition, agent definition, Workspace policy, governed default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....services.context_routing_policy import (
    ContextRoutingDecision,
    ContextRoutingSignals,
    evaluate_context_routing,
)

TOOL_SURFACE_UNRESOLVED = "unresolved"


@dataclass(slots=True)
class ContextPlan:
    tier: str
    include_tools: bool
    include_system_context: bool
    include_skills: bool
    include_recent_history: bool
    include_summary_context: bool
    include_agent_blueprint: bool
    recent_history_limit: int
    system_prompt_variant: str
    route_reason: str
    token_budget: int
    domains: list[str]
    tool_allowlist: list[str] | None
    skill_terms: list[str]
    blocked_tools: list[str]
    required_domains: list[str]
    enforce_domain_coverage: bool
    scenario_profile_id: str
    scenario_profile_name: str
    budget_profile_id: str = ""
    budget_profile_name: str = ""
    similar_session_avg_tokens: int = 0
    budget_breakdown: dict[str, int] | None = None
    routing_rule_id: str = ""
    routing_rule_source: str = "default_policy"
    tool_surface_source: str = TOOL_SURFACE_UNRESOLVED
    # The governed default set's key (``diagnosis.v1``); empty for every other surface source.
    tool_surface_set: str = ""


def context_plan_log_fields(context_plan: ContextPlan) -> dict[str, str]:
    """The planned turn's identity for the ``agent.prepare.context_planned`` log."""
    return {
        "tier": context_plan.tier,
        "route_reason": context_plan.route_reason,
        "tool_surface_source": context_plan.tool_surface_source,
        "tool_surface_set": context_plan.tool_surface_set,
    }


def classify_context_route(context_plan: ContextPlan) -> str:
    route_reason = str(context_plan.route_reason or "").strip()
    if route_reason == "change_or_continuation":
        return "coding_change"
    if route_reason == "admin_capability" or context_plan.tier == "full":
        return "broad_diagnosis"
    return "targeted_diagnosis"


def _section_decision(
    context_plan: ContextPlan,
    *,
    included: bool,
    include_reason: str,
    skip_reason: str,
    source: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario_name = str(context_plan.scenario_profile_name or "").strip()
    payload: dict[str, Any] = {
        "included": bool(included),
        "reason": include_reason if included else skip_reason,
        "route_class": classify_context_route(context_plan),
        "route_reason": str(context_plan.route_reason or "").strip(),
        "source": source or ("scenario_profile" if scenario_name else "context_plan"),
    }
    if scenario_name:
        payload["scenario_profile_name"] = scenario_name
    if extra:
        payload.update(extra)
    return payload


def build_context_section_decisions(context_plan: ContextPlan) -> dict[str, dict[str, Any]]:
    surface = ":".join(part for part in (context_plan.tool_surface_source, context_plan.tool_surface_set) if part)
    return {
        "tools": _section_decision(
            context_plan,
            included=context_plan.include_tools,
            include_reason=f"tool surface from {surface}",
            skip_reason=f"tool surface {surface}",
            source=f"tool_surface:{surface}",
            extra={
                "allowlist_count": len(context_plan.tool_allowlist or []),
                "blocked_count": len(context_plan.blocked_tools or []),
                "tool_surface_set": context_plan.tool_surface_set,
            },
        ),
        "system_context": _section_decision(
            context_plan,
            included=context_plan.include_system_context,
            include_reason="route requires broader operational context",
            skip_reason="standard route does not include system context",
        ),
        "skills": _section_decision(
            context_plan,
            included=context_plan.include_skills,
            include_reason="route can use skill discovery context",
            skip_reason="skill discovery is not needed",
        ),
        "recent_history": _section_decision(
            context_plan,
            included=context_plan.include_recent_history,
            include_reason="route depends on recent conversation continuity",
            skip_reason="recent history is not needed",
            extra={"recent_history_limit": int(context_plan.recent_history_limit or 0)},
        ),
        "summary_context": _section_decision(
            context_plan,
            included=context_plan.include_summary_context,
            include_reason="route can use persisted session summary context",
            skip_reason="summary context is not needed",
        ),
        "agent_blueprint": _section_decision(
            context_plan,
            included=context_plan.include_agent_blueprint,
            include_reason="route executes with an agent blueprint",
            skip_reason="agent blueprint is not needed",
        ),
    }


def _plan(decision: ContextRoutingDecision, **overrides: Any) -> ContextPlan:
    """Build a ContextPlan for a routing decision; the tool surface stays unresolved."""
    values: dict[str, Any] = {
        "tier": decision.tier,
        "include_tools": False,
        "include_system_context": False,
        "include_skills": False,
        "include_recent_history": False,
        "include_summary_context": False,
        "include_agent_blueprint": False,
        "recent_history_limit": 0,
        "system_prompt_variant": "standard",
        "route_reason": decision.route_reason,
        "token_budget": 8000,
        "domains": [],
        "tool_allowlist": None,
        "skill_terms": [],
        "blocked_tools": [],
        "required_domains": [],
        "enforce_domain_coverage": False,
        "scenario_profile_id": "",
        "scenario_profile_name": "",
        "routing_rule_id": decision.rule_id,
        "routing_rule_source": decision.source,
    }
    values.update(overrides)
    return ContextPlan(**values)


def plan_turn_context(
    *,
    capability_type: str = "diagnosis",
    is_change_mode: bool = False,
    project_id: str | None,
    agent_definition: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
    history_count: int,
    project_config: dict[str, Any] | None = None,
) -> ContextPlan:
    """Plan the turn's context from explicit inputs only; the prompt is not an input."""
    metadata = session_metadata or {}
    has_summary = bool(metadata.get("summary"))
    effective_capability = str(capability_type or "diagnosis").strip().lower() or "diagnosis"
    is_admin_agent = effective_capability == "admin"
    signals = ContextRoutingSignals(
        is_admin_agent=is_admin_agent,
        is_change_agent=is_change_mode or effective_capability == "change" or bool(agent_definition),
        has_task_context=bool(metadata.get("task_id")),
        has_parent_context=bool(metadata.get("parent_session_id")),
        has_project=bool(project_id),
        history_count=history_count,
        has_summary=has_summary,
    )
    decision = evaluate_context_routing(signals, project_config)
    long_conversation = history_count > 8 or has_summary

    if decision.rule_id in {"admin_capability", "change_or_continuation"}:
        return _plan(
            decision,
            include_system_context=True,
            include_skills=True,
            include_recent_history=True,
            include_summary_context=True,
            include_agent_blueprint=bool(agent_definition),
            recent_history_limit=8,
            system_prompt_variant="admin" if decision.rule_id == "admin_capability" else "full",
            token_budget=26000 if decision.rule_id == "admin_capability" else 24000,
        )

    if decision.rule_id == "contextual_request":
        return _plan(
            decision,
            include_recent_history=True,
            include_summary_context=long_conversation,
            recent_history_limit=6,
            token_budget=10000,
        )

    # default_standard: a fresh conversation outside a Workspace (no history, no summary).
    return _plan(
        decision,
        include_recent_history=history_count > 0,
        include_summary_context=long_conversation,
        recent_history_limit=4,
    )
