"""Preparation helpers for the agent run loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ....models import Message, Session
from ....runtime_limits import MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS, MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS
from ....services.model_gateway.litellm import admit_gateway_runtimes
from ....services.model_selection.chain_admission import admit_runtime_chain
from ....services.system_config import get_agent_runtime_settings
from ..types import (
    ChatMessage,
    RuntimeSettings,
    RuntimeTarget,
    ToolDefinition,
)
from .run_context_history import build_history, fit_context_budget
from .run_context_knowledge import plan_context, resolve_knowledge_and_entities, resolve_repository_and_grounding
from .run_context_project import resolve_project_and_tool_surface
from .run_context_session import load_turn_history, open_run
from .run_context_state import AgentRunRequest, RunPreparation
from .run_context_system_prompt import compose_system_prompt_and_messages
from .run_context_tool_offer import build_tool_context, offer_tool_definitions

logger = logging.getLogger(__name__)

_SESSION_RUNTIME_TIMEOUT_BOUNDS = (
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
)


def _runtime_settings_with_session_overrides(
    base_runtime_settings: dict[str, Any],
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Allow a narrow, validated subset of per-session runtime setting overrides.

    This keeps the global runtime contract stable while letting bounded delegated
    runs opt into a validated timeout budget.
    """

    runtime_settings = dict(base_runtime_settings)
    raw_timeout_seconds = session_metadata.get("runtime_request_timeout_seconds")
    try:
        timeout_seconds = int(raw_timeout_seconds)
    except (TypeError, ValueError):
        timeout_seconds = 0
    if timeout_seconds > 0:
        minimum, maximum = _SESSION_RUNTIME_TIMEOUT_BOUNDS
        runtime_settings["runtime_request_timeout_seconds"] = max(minimum, min(timeout_seconds, maximum))
    return runtime_settings


@dataclass
class PreparedAgentRun:
    current_session: Session | None
    session_metadata: dict[str, Any]
    agent_mode: Any
    capability_type: str
    personality_prompt: str
    memory_prompt: str
    skills_prompt: str
    repo_microagents_prompt: str
    repo_knowledge_prompt: str
    system_prompt: str
    system_context: dict[str, Any] | None
    context_plan: Any
    history_count: int
    history: list[Message]
    summary_context_msgs: list[ChatMessage]
    messages: list[ChatMessage]
    current_turn_content: str
    tool_definitions: list[ToolDefinition]
    tool_context: ToolContext
    runtimes: list[RuntimeTarget]
    existing_thread_context: dict[str, Any]
    runtime_settings: RuntimeSettings
    tool_domain_config: dict[str, Any]
    session_entities: list[dict[str, Any]]


async def _admit_runtimes(request: AgentRunRequest, state: RunPreparation) -> None:
    """Resolve the runtime chain through the admission boundary and the turn's runtime settings."""
    db, project_id, session_metadata = request.db, request.project_id, state.session_metadata
    project_config = state.project_config
    runtimes = await request.resolve_control_plane_runtimes_func(db, runtime_target_id=request.runtime_target_id)
    state.runtimes = await admit_gateway_runtimes(
        db,
        await admit_runtime_chain(
            db, runtimes, project_config=project_config, project_id=project_id, session_metadata=session_metadata
        ),
        project_config=project_config,
        project_id=project_id,
        session_metadata=session_metadata,
    )
    base_runtime_settings = await get_agent_runtime_settings(db)
    # Reasoning strategies do not pick a turn's runtime, so the loop does not load them.
    runtime_settings = dict(base_runtime_settings)
    state.runtime_settings = _runtime_settings_with_session_overrides(runtime_settings, session_metadata)


def _prepared_agent_run(state: RunPreparation) -> PreparedAgentRun:
    return PreparedAgentRun(
        current_session=state.current_session,
        session_metadata=state.session_metadata,
        agent_mode=state.agent_mode,
        capability_type=state.capability_type,
        personality_prompt=state.personality_prompt,
        memory_prompt=state.memory_prompt,
        skills_prompt=state.skills_prompt,
        repo_microagents_prompt=state.repo_microagents_prompt,
        repo_knowledge_prompt=state.repo_knowledge_prompt,
        system_prompt=state.system_prompt,
        system_context=state.system_context,
        context_plan=state.context_plan,
        history_count=len(state.all_history),
        history=state.history,
        summary_context_msgs=state.summary_context_msgs,
        messages=state.messages,
        current_turn_content=state.current_turn_content,
        tool_definitions=state.tool_definitions,
        tool_context=state.tool_context,
        runtimes=state.runtimes,
        existing_thread_context=state.existing_thread_context,
        runtime_settings=state.runtime_settings,
        tool_domain_config=state.tool_domain_config,
        session_entities=state.session_entities,
    )


async def _prepare(request: AgentRunRequest) -> PreparedAgentRun:
    """Run the preparation stages in their fixed order; each stage may read and flush the session."""
    state = await open_run(request)
    await load_turn_history(request, state)
    await plan_context(request, state)
    await resolve_knowledge_and_entities(request, state)
    await resolve_project_and_tool_surface(request, state)
    await resolve_repository_and_grounding(request, state)
    await fit_context_budget(request, state)
    build_history(state)
    await compose_system_prompt_and_messages(request, state)
    await _admit_runtimes(request, state)
    state.tool_context = await build_tool_context(request, state)
    await offer_tool_definitions(request, state)
    # No prompt-regex prefetch: cache warming never decides what runs.
    logger.info(
        "agent.prepare.complete",
        extra={
            "session_id": request.session_id,
            "history_count": len(state.all_history),
            "tool_definition_count": len(state.tool_definitions),
            "runtime_count": len(state.runtimes),
        },
    )
    return _prepared_agent_run(state)


async def prepare_agent_run(
    *,
    db: AsyncSession,
    session_id: str,
    user_message: str,
    user_id: str,
    project_id: str | None,
    agent_type: str,
    runtime_target_id: str | None,
    thinking_level: str | None,
    agent_definition: dict | None,
    parent_session_id: str | None,
    sub_agent_depth: int,
    workspace_root: str,
    resolve_model_context_cap: Any,
    resolve_control_plane_runtimes_func: Any,
    filter_tool_definitions: Any,
    exclude_tool_definitions: Any,
    trim_messages_to_budget: Any,
) -> PreparedAgentRun:
    logger.info(
        "agent.prepare.start", extra={"session_id": session_id, "project_id": project_id, "agent_type": agent_type}
    )
    return await _prepare(
        AgentRunRequest(
            db=db,
            session_id=session_id,
            user_message=user_message,
            user_id=user_id,
            project_id=project_id,
            agent_type=agent_type,
            runtime_target_id=runtime_target_id,
            thinking_level=thinking_level,
            agent_definition=agent_definition,
            parent_session_id=parent_session_id,
            sub_agent_depth=sub_agent_depth,
            workspace_root=workspace_root,
            resolve_model_context_cap=resolve_model_context_cap,
            resolve_control_plane_runtimes_func=resolve_control_plane_runtimes_func,
            filter_tool_definitions=filter_tool_definitions,
            exclude_tool_definitions=exclude_tool_definitions,
            trim_messages_to_budget=trim_messages_to_budget,
        )
    )
