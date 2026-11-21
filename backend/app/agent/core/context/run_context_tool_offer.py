"""Preparation stages that build the turn's tool context and the tool definitions it offers."""

from __future__ import annotations

from app.services.execution_profile_trace import execution_profile_trace_summary
from app.tools.context import ToolContext

from ....services.chat_deferred_tools import defer_chat_tools
from ....services.governed_default_tool_sets import governed_default_tool_set
from ....services.request_context import get_current_request_id
from ....services.session.turn_tool_surface_record import TOOL_SURFACE_GOVERNED_DEFAULT, TOOL_SURFACE_WORKSPACE_POLICY
from ....tools.registry import get_all_tools_with_plugins
from .run_context_state import AgentRunRequest, RunPreparation
from .run_context_tooling import build_run_context_tool_definitions, record_offered_tool_decision


async def build_tool_context(request: AgentRunRequest, state: RunPreparation) -> ToolContext:
    """The tool context of this turn; a chat turn with connector writes also gets its role grant and plan notes."""
    db, session_metadata, runtimes = request.db, state.session_metadata, state.runtimes
    run_capability = state.routing_resolution.run_capability
    tool_context = ToolContext(
        user_id=request.user_id, project_ids=state.user_project_ids, roles=state.user_roles,
        session_id=request.session_id,
        project_config=state.project_config,
        current_user_message=state.current_turn_content,
        session_data_policy=session_metadata.get("data_policy"),
        db=db,
        workspace_root=str(state.tool_workspace_root),
        system_context=state.system_context,
        parent_session_id=request.parent_session_id,
        sub_agent_depth=request.sub_agent_depth,
        agent_definition=request.agent_definition,
        capability_type=state.capability_type,
        agent_mode_key=state.agent_mode.key if state.agent_mode else None,
        run_capability=run_capability.tool_context_state(),
        request_id=get_current_request_id(),
        prompt_config=state.prompt_config_metadata,
        execution_profile_trace=execution_profile_trace_summary(session_metadata.get("execution_profile")),
        turn_model=(str((runtimes[0] or {}).get("model") or "") or None) if runtimes else None,
    )
    if run_capability.chat_connector_writes:
        from ....services.work_role_model.surfaces import chat_turn_grant, prompt_note, with_prompt_note

        # Role-based tools: the chat offers the person's roles' tools;
        # with no role it has none and says why. Inert while the Workspace switch is off.
        tool_context.work_role_grant = await chat_turn_grant(
            db, user_id=request.user_id, workspace_id=request.project_id
        )
        state.messages = with_prompt_note(state.messages, prompt_note(tool_context.work_role_grant))
        # A turn restarted by the person's plan confirmation performs the plan, never proposes it again.
        from ....services.run_capability.chat_write_plan import confirmed_plan_note

        state.messages = with_prompt_note(state.messages, confirmed_plan_note(session_metadata))
    return tool_context


def _dynamic_database_tool_loader(include_tools: bool):
    if not include_tools:
        return None
    try:
        from ....services.dynamic_tool_definitions import list_runtime_dynamic_tool_definitions

        return list_runtime_dynamic_tool_definitions
    except ImportError:
        return None


async def offer_tool_definitions(request: AgentRunRequest, state: RunPreparation) -> None:
    """Build the offered tool definitions, defer a chat turn's non-core tools and record what was offered."""
    context_plan, tool_context = state.context_plan, state.tool_context
    tool_definitions = await build_run_context_tool_definitions(
        db=request.db,
        tool_context=tool_context,
        capability_type=state.capability_type,
        include_tools=context_plan.include_tools,
        tool_allowlist=context_plan.tool_allowlist,
        blocked_tools=context_plan.blocked_tools,
        agent_definition=request.agent_definition,
        get_all_tools_with_plugins=get_all_tools_with_plugins,
        filter_tool_definitions=request.filter_tool_definitions,
        exclude_tool_definitions=request.exclude_tool_definitions,
        list_dynamic_database_tool_definitions=_dynamic_database_tool_loader(context_plan.include_tools),
        workflow_routing_policy_resolution=state.tool_routing_resolution,
    )
    if state.chat_connector_writes and context_plan.tool_surface_source in {
            TOOL_SURFACE_GOVERNED_DEFAULT, TOOL_SURFACE_WORKSPACE_POLICY}:
        # A chat turn sends its core tools in full and the rest by name (``chat_deferred_tools``); a
        # workflow run's phase turn never gets here (no chat writes) and keeps its phase-only surface.
        surface_set = str(context_plan.tool_surface_set or "").split(".v")[0]
        if state.chat_choice_settled:
            tool_definitions = [definition for definition in tool_definitions
                                if (definition.get("function") or {}).get("name") != "select_workflow"]
        tool_definitions = defer_chat_tools(
            tool_definitions, families=governed_default_tool_set(surface_set).families if surface_set else (),
            history=state.all_history, context=tool_context)
    strategy_decision = state.strategy_decision
    record_offered_tool_decision(
        session_metadata=state.session_metadata, current_session=state.current_session, tool_context=tool_context,
        routing_resolution=state.tool_routing_resolution, workflow_contract=strategy_decision.workflow_contract,
        tool_definitions=tool_definitions, workflow_id=strategy_decision.workflow_id,
        agent_definition=request.agent_definition,
    )
    state.tool_definitions = tool_definitions
