"""Preparation stages that fit the context budget and build the history the prompt carries."""

from __future__ import annotations

from ....services.context_budget import apply_adaptive_context_budget
from ....services.context_compaction import (
    ensure_session_context_compaction,
    render_context_compaction_for_prompt,
)
from ....services.instructions.resolve import prepare_turn_instructions
from ..guards.response_guards import get_step_allowed_tools
from ..runtime.summarizer import build_history_messages
from .run_context_messages import prepend_structured_thread_context
from .run_context_state import AgentRunRequest, RunPreparation


def _estimated_tool_count(request: AgentRunRequest, state: RunPreparation) -> int:
    context_plan, agent_definition = state.context_plan, request.agent_definition
    if not context_plan.include_tools:
        return 0
    if context_plan.tool_allowlist:
        return len(context_plan.tool_allowlist)
    if agent_definition:
        return len(
            {
                tool_name
                for step in agent_definition.get("steps", [])
                if step.get("isEnabled") or step.get("is_enabled")
                for tool_name in get_step_allowed_tools(step)
            }
        )
    return 4 if state.capability_type == "change" else 2


async def _compact_session_context(request: AgentRunRequest, state: RunPreparation) -> None:
    current_session, context_plan = state.current_session, state.context_plan
    if current_session is None or not context_plan.include_recent_history:
        return
    context_compaction = await ensure_session_context_compaction(
        request.db,
        session_id=request.session_id,
        messages=state.all_history,
        recent_window=context_plan.recent_history_limit,
    )
    state.context_compaction_prompt = render_context_compaction_for_prompt(context_compaction)
    if context_compaction is not None:
        state.session_metadata["runtime_context_compaction"] = {
            "id": context_compaction.id,
            "status": context_compaction.status,
            "compaction_index": context_compaction.compaction_index,
            "source_first_message_id": context_compaction.source_first_message_id,
            "source_last_message_id": context_compaction.source_last_message_id,
            "source_message_count": context_compaction.source_message_count,
            "recent_message_count": context_compaction.recent_message_count,
        }
        current_session.metadata_ = state.session_metadata
        await request.db.flush()


async def fit_context_budget(request: AgentRunRequest, state: RunPreparation) -> None:
    """Size the token budget for this turn, compact older history and add the bound instructions."""
    db, session_metadata = request.db, state.session_metadata
    context_plan = await apply_adaptive_context_budget(
        db,
        context_plan=state.context_plan,
        project_id=request.project_id,
        agent_type=state.agent_type,
        capability_type=state.capability_type,
        history_count=len(state.all_history),
        entity_count=len(state.session_entities),
        tool_count=_estimated_tool_count(request, state),
        has_parent_context=bool(request.parent_session_id or session_metadata.get("parent_session_id")),
        sub_agent_depth=request.sub_agent_depth,
        scenario_budget_override=state.scenario_budget_override,
    )
    if state.model_context_cap:
        context_plan.token_budget = min(int(context_plan.token_budget), int(state.model_context_cap))
    state.context_plan = context_plan
    await _compact_session_context(request, state)
    # The explicitly bound instructions (agent → Workspace → workflow), recorded key@version on the session.
    instructions_section = await prepare_turn_instructions(
        db, session_metadata=session_metadata, project_id=request.project_id, agent_definition=request.agent_definition
    )
    if state.current_session is not None:
        state.current_session.metadata_ = session_metadata
        await db.flush()
    state.evidence_grounding_prompt = "\n\n".join(
        item for item in (state.evidence_grounding_prompt, instructions_section) if item
    )


def build_history(state: RunPreparation) -> None:
    """Split the stored history into the summary context and the recent messages the plan includes."""
    context_plan = state.context_plan
    references = state.session_summary_references
    summary_context_msgs, history = build_history_messages(
        state.all_history,
        state.session_summary,
        include_summary=context_plan.include_summary_context,
        recent_window=context_plan.recent_history_limit,
        summary_references=references if isinstance(references, list) else None,
    )
    if not context_plan.include_recent_history:
        history = []
        summary_context_msgs = []
    state.history = history
    state.summary_context_msgs = prepend_structured_thread_context(
        summary_context_msgs=summary_context_msgs,
        context_tier=context_plan.tier,
        existing_thread_context=state.existing_thread_context,
    )
