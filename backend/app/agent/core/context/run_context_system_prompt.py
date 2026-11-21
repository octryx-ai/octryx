"""Preparation stage that composes the system prompt and the message list sent to the model."""

from __future__ import annotations

from app.tools.runtime_impl._runtime_cli_helpers import detect_system_context

from ....services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from ..prompts.agent_blueprint import ensure_reply_format_section
from ..prompts.prompt_builder import build_system_prompt_parts
from .run_context_messages import build_prompt_messages
from .run_context_state import AgentRunRequest, RunPreparation


async def _workflow_catalog_prompt(request: AgentRunRequest, state: RunPreparation) -> str:
    from ....services.workflow_routing.model_catalog import (
        build_model_workflow_catalog,
        render_model_workflow_catalog_prompt,
    )
    from ....services.workflow_routing.settled_choice import workflow_choice_settled

    # The catalog is how a model reaches select_workflow; a turn without tools gets none, and neither does a
    # chat turn whose router or composer already settled the workflow (``settled_choice``).
    state.chat_choice_settled = bool(state.chat_connector_writes) and workflow_choice_settled(
        state.session_metadata.get(ROUTING_RESOLUTION_KEY))
    if not state.context_plan.include_tools or state.chat_choice_settled:
        return ""
    return render_model_workflow_catalog_prompt(
        await build_model_workflow_catalog(request.db, project_id=request.project_id)
    )


def _system_context(state: RunPreparation) -> dict | None:
    system_context = (
        detect_system_context(str(state.tool_workspace_root)) if state.context_plan.include_system_context else None
    )
    session_metadata = state.session_metadata
    coding_run_context = (
        session_metadata.get("coding_run") if isinstance(session_metadata.get("coding_run"), dict) else None
    )
    if coding_run_context:
        system_context = {**(system_context or {}), "coding_run": coding_run_context}
    return system_context


async def compose_system_prompt_and_messages(request: AgentRunRequest, state: RunPreparation) -> None:
    """Build the system prompt from every resolved fragment, then the trimmed message list around it."""
    state.system_context = _system_context(state)
    workflow_catalog_prompt = await _workflow_catalog_prompt(request, state)
    context_plan, agent_definition = state.context_plan, request.agent_definition
    system_prompt_parts = build_system_prompt_parts(
        agent_type=state.agent_type,
        agent_mode=state.agent_mode,
        personality=state.personality_prompt,
        memory=state.memory_prompt,
        skills=state.skills_prompt,
        entity_context=state.entity_context_prompt,
        context_compaction=state.context_compaction_prompt,
        checkpoint_context=state.checkpoint_context_prompt,
        evidence_grounding=state.evidence_grounding_prompt,
        repo_microagents=state.repo_microagents_prompt,
        repo_knowledge=state.repo_knowledge_prompt,
        system_context=state.system_context,
        thinking_level=request.thinking_level,
        agent_definition=agent_definition if context_plan.include_agent_blueprint else None,
        prompt_variant=context_plan.system_prompt_variant,
        prompt_variant_routing=state.system_prompt_variant_routing,
        workflow_catalog=workflow_catalog_prompt,
    )
    system_prompt_parts = ensure_reply_format_section(system_prompt_parts, agent_definition)
    state.system_prompt = system_prompt_parts.combined

    current_turn_message = state.current_turn_message
    state.current_turn_content = (current_turn_message.content if current_turn_message else request.user_message) or ""
    state.messages = build_prompt_messages(
        system_prompt_parts=system_prompt_parts,
        summary_context_msgs=state.summary_context_msgs,
        history=state.history,
        current_turn_content=state.current_turn_content,
        trim_messages_to_budget=request.trim_messages_to_budget,
        token_budget=int(context_plan.token_budget or 0),
    )
