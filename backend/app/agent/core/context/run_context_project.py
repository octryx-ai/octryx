"""Preparation stage that resolves the turn's project configuration, tool surface and prompt variant."""

from __future__ import annotations

from ....services.execution_profile_requirements import (
    apply_requirement_decision_to_profile,
    evaluate_workflow_tool_requirements,
)
from ..prompts.prompt_templates import (
    build_system_prompt_config_metadata,
    load_system_prompt_variant_routing,
    resolve_effective_system_prompt_config,
)
from .run_context_config import assemble_turn_project_config
from .run_context_state import AgentRunRequest, RunPreparation
from .run_context_tool_policy import tool_routing_resolution_for_turn
from .turn_tool_surface import plan_and_record_turn_tool_surface


async def _resolve_prompt_config(request: AgentRunRequest, state: RunPreparation) -> None:
    effective_prompt_config = resolve_effective_system_prompt_config(
        prompt_variant_routing=await load_system_prompt_variant_routing(request.db),
        project_config=state.project_config,
        project_id=request.project_id,
    )
    state.system_prompt_variant_routing = effective_prompt_config.variant_routing
    state.prompt_config_metadata = build_system_prompt_config_metadata(
        requested_variant=state.context_plan.system_prompt_variant,
        prompt_variant_routing=state.system_prompt_variant_routing,
        routing_sources=effective_prompt_config.routing_sources,
        scope=effective_prompt_config.scope,
    )


async def resolve_project_and_tool_surface(request: AgentRunRequest, state: RunPreparation) -> None:
    """Assemble the project config, plan the tool surface and record the workflow's tool requirements."""
    db, project_id, session_metadata = request.db, request.project_id, state.session_metadata
    strategy_decision = state.strategy_decision
    turn_project_config = await assemble_turn_project_config(
        db=db,
        user_id=request.user_id,
        project_id=project_id,
        user_roles=state.user_roles,
        workspace_root=request.workspace_root,
        session_metadata=session_metadata,
        engineering_runtime_metadata=state.engineering_runtime_metadata,
    )
    project_config = state.project_config = turn_project_config.project_config
    # The tool surface comes from explicit sources only: selected definition, selected
    # workflow, agent definition, Workspace tool policy, governed default.
    state.tool_routing_resolution = tool_routing_resolution_for_turn(session_metadata)
    run_capability = state.routing_resolution.run_capability
    state.context_plan = plan_and_record_turn_tool_surface(
        state.context_plan, session_id=request.session_id, session_metadata=session_metadata,
        current_session=state.current_session, capability_type=state.capability_type,
        strategy_decision=strategy_decision, routing_resolution=state.tool_routing_resolution,
        agent_definition=request.agent_definition, project_config=project_config,
        capability_class=run_capability.capability_class,
        chat_connector_writes=run_capability.chat_connector_writes,
    )
    user_project_ids = list(turn_project_config.user_project_ids or [])
    # The run acts within the session's project: policy checks (repository
    # operations, resource scoping) must see it even when the acting user is
    # not a direct member — otherwise session-scoped work fails with
    # misleading "not configured" denials.
    if project_id and project_id not in user_project_ids:
        user_project_ids.append(project_id)
    state.user_project_ids = user_project_ids
    state.tool_workspace_root = turn_project_config.tool_workspace_root
    await _resolve_prompt_config(request, state)
    requirement_decision = evaluate_workflow_tool_requirements(
        workflow_contract=strategy_decision.workflow_contract,
        project_config=project_config,
    )
    state.execution_profile_metadata = apply_requirement_decision_to_profile(
        state.execution_profile_metadata, requirement_decision
    )
    session_metadata["execution_profile"] = state.execution_profile_metadata
