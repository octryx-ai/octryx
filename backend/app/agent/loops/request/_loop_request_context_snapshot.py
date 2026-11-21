"""Turn context snapshot (the trace record) for a standard loop request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....services.prompt_catalog import PROMPT_TEMPLATES_TRACE_KEY, bound_prompt_trace_record
from ....services.workflow_runs.phase_workspace import run_copy_trace_fields
from ...core.context.context_planner import build_context_section_decisions, classify_context_route
from ...core.guards.tdd_cycle import export_tdd_cycle_state, is_tdd_cycle_step
from ...core.runtime.trace_runtime import build_turn_context_snapshot, compact_trace_value

if TYPE_CHECKING:
    from ._loop_request_messages import RuntimeMessagesInputs


def _order_domains_for_trace(domains: list[Any], request_analysis: dict[str, Any]) -> list[str]:
    """analysis_only: orders the explicit domains for the trace; never adds, drops or requires one."""
    seen: set[str] = set()
    unique = [
        domain
        for domain in (str(item).strip().lower() for item in domains if str(item).strip())
        if not (domain in seen or seen.add(domain))
    ]
    text = str(
        request_analysis.get("canonical_message")
        or request_analysis.get("source_message")
        or ""
    ).lower()
    if not text:
        return unique
    return sorted(unique, key=lambda domain: (text.find(domain) if domain in text else 1_000_000, unique.index(domain)))


def _context_plan_trace(context_plan: Any, request_analysis: dict[str, Any]) -> dict[str, Any]:
    effective_context_domains = _order_domains_for_trace(
        list(context_plan.domains or request_analysis.get("requested_domains") or []),
        request_analysis,
    )
    effective_required_domains = _order_domains_for_trace(
        list(context_plan.required_domains or request_analysis.get("required_domains") or []),
        request_analysis,
    )
    effective_enforce_domain_coverage = bool(context_plan.enforce_domain_coverage)
    return {
        "tier": context_plan.tier,
        "route_reason": context_plan.route_reason,
        "token_budget": context_plan.token_budget,
        "include_tools": context_plan.include_tools,
        "tool_surface_source": getattr(context_plan, "tool_surface_source", ""),
        "tool_surface_set": getattr(context_plan, "tool_surface_set", ""),
        "include_system_context": context_plan.include_system_context,
        "include_skills": context_plan.include_skills,
        "include_recent_history": context_plan.include_recent_history,
        "include_summary_context": context_plan.include_summary_context,
        "domains": effective_context_domains,
        "tool_allowlist": context_plan.tool_allowlist or [],
        "skill_terms": context_plan.skill_terms,
        "blocked_tools": context_plan.blocked_tools,
        "required_domains": effective_required_domains,
        "enforce_domain_coverage": effective_enforce_domain_coverage,
        "scenario_profile_id": context_plan.scenario_profile_id,
        "scenario_profile_name": context_plan.scenario_profile_name,
        "budget_profile_id": getattr(context_plan, "budget_profile_id", ""),
        "budget_profile_name": getattr(context_plan, "budget_profile_name", ""),
        "similar_session_avg_tokens": getattr(context_plan, "similar_session_avg_tokens", 0),
        "budget_breakdown": getattr(context_plan, "budget_breakdown", {}) or {},
        "route_class": classify_context_route(context_plan),
        "section_decisions": build_context_section_decisions(context_plan),
    }


def _add_turn_state_trace(
    context_snapshot: dict[str, Any],
    inputs: RuntimeMessagesInputs,
    effective_workflow_contract: dict[str, Any] | None,
) -> None:
    runtime_settings = inputs.runtime_settings
    tool_context = inputs.tool_context
    system_context = inputs.system_context
    if inputs.current_subtask_role:
        context_snapshot["subtask_model_role"] = inputs.current_subtask_role
    if inputs.current_coding_discipline:
        context_snapshot["coding_discipline"] = inputs.current_coding_discipline
    if isinstance(system_context, dict) and isinstance(system_context.get("coding_run"), dict):
        context_snapshot["coding_run"] = compact_trace_value(
            system_context["coding_run"],
            trace_limits=runtime_settings,
        )
    context_snapshot["sub_agent_depth"] = int(getattr(tool_context, "sub_agent_depth", 0) or 0)
    # A run phase's tools work in the run's working copy: the trace names it and the run's base.
    context_snapshot.update(run_copy_trace_fields(getattr(tool_context, "project_config", None)))
    # Every catalog prompt this turn rendered so far, as key@version + digest (audit).
    context_snapshot[PROMPT_TEMPLATES_TRACE_KEY] = bound_prompt_trace_record()
    context_snapshot["reasoning_task_type"] = inputs.current_reasoning_task_type
    context_snapshot["reasoning_stage"] = inputs.current_reasoning_stage
    context_snapshot["elastic_iteration"] = compact_trace_value(inputs.elastic_iteration, trace_limits=runtime_settings)
    current_step = inputs.current_step
    if current_step and is_tdd_cycle_step(current_step) and inputs.tdd_cycle_state is not None:
        context_snapshot["tdd_cycle"] = compact_trace_value(
            export_tdd_cycle_state(inputs.tdd_cycle_state), trace_limits=runtime_settings
        )
    context_snapshot["turn_diff"] = compact_trace_value(
        inputs.turn_diff_tracker.to_dict(), trace_limits=runtime_settings
    )
    if inputs.existing_thread_context:
        context_snapshot["thread_context"] = compact_trace_value(
            inputs.existing_thread_context, trace_limits=runtime_settings
        )


def build_request_context_snapshot(
    inputs: RuntimeMessagesInputs,
    effective_workflow_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """The turn's context snapshot before the tool surface of this iteration is decided."""
    tool_context = inputs.tool_context
    context_plan = _context_plan_trace(inputs.context_plan, inputs.request_analysis)
    context_snapshot = build_turn_context_snapshot(
        system_prompt=inputs.system_prompt,
        personality_prompt=inputs.personality_prompt,
        memory_prompt=inputs.memory_prompt,
        skills_prompt=inputs.skills_prompt,
        summary_context_messages=inputs.summary_context_msgs,
        history=inputs.history,
        thinking_level=inputs.thinking_level,
        runtime_target_id=inputs.runtime_target_id,
        system_context=inputs.system_context,
        agent_definition=inputs.agent_definition,
        current_step=inputs.current_step_for_runtime,
        current_step_index=inputs.current_step_index + 1 if inputs.current_step else 0,
        request_id=tool_context.request_id,
        context_plan=context_plan,
        prompt_config=getattr(tool_context, "prompt_config", None),
        request_analysis=inputs.request_analysis,
        trace_limits=inputs.runtime_settings,
        execution_profile_trace=getattr(tool_context, "execution_profile_trace", None),
    )
    _add_turn_state_trace(context_snapshot, inputs, effective_workflow_contract)
    return context_snapshot
