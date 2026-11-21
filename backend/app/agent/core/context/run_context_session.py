"""Preparation stages that open the run: session, routing, agent mode and the stored history."""

from __future__ import annotations

from sqlalchemy import select

from ....models import Message, Personality, Role, Session, ThreadContext, UserRole
from ....services.agent_mode import resolve_agent_mode
from ....services.policy_lists.live import refresh_live_policy_lists
from ....services.prompt_catalog import bind_prompt_set
from ....services.prompt_catalog.turn import resolve_turn_prompt_set
from ....services.system_config import get_agent_tool_domain_config
from .run_context_messages import split_current_turn_from_history
from .run_context_routing import resolve_turn_routing_profile
from .run_context_state import AgentRunRequest, RunPreparation
from .runtime_readiness_history import exclude_runtime_readiness_blocked_turns

# Unbounded fetch causes O(n) memory growth on long sessions
_MAX_HISTORY_MESSAGES = 1000


async def _load_session(request: AgentRunRequest) -> Session | None:
    db = request.db
    session_result = await db.execute(select(Session).where(Session.id == request.session_id))
    current_session = session_result.scalar_one_or_none()
    # An agent run never works in somebody else's private Workspace (flows and
    # workers take the project from the request; the run would read that Workspace's knowledge for the caller).
    from ....services.project.private_workspace import refuse_foreign_private  # noqa: PLC0415

    session_project_id = current_session.project_id if current_session is not None else None
    for scope in {request.project_id, session_project_id} - {None, ""}:
        if await refuse_foreign_private(db, str(scope), str(request.user_id)):
            raise PermissionError("private_workspace: this run cannot use somebody else's private Workspace")
    return current_session


async def open_run(request: AgentRunRequest) -> RunPreparation:
    """Load the session, bind the turn's prompts, resolve routing and the agent mode."""
    db = request.db
    current_session = await _load_session(request)
    session_metadata = dict(current_session.metadata_ or {}) if current_session else {}
    await refresh_live_policy_lists(db)  # admin-edited policy lists are live from this turn on
    # The turn's prompt texts, resolved once (agent definition > Workspace > global > seed).
    bind_prompt_set(
        await resolve_turn_prompt_set(db, project_id=request.project_id)
    )
    routing_resolution = await resolve_turn_routing_profile(
        db=db,
        session_metadata=session_metadata,
        user_message=request.user_message,
        agent_type=request.agent_type,
        project_id=request.project_id,
        agent_definition=request.agent_definition,
        runtime_target_id=request.runtime_target_id,
        parent_session_id=request.parent_session_id, session_id=request.session_id, user_id=request.user_id,
    )
    state = RunPreparation(
        current_session=current_session,
        session_metadata=session_metadata,
        routing_resolution=routing_resolution,
        # A governed run's mode comes from its run capability, not from the request.
        agent_type=routing_resolution.run_capability.effective_agent_type or request.agent_type,
        execution_profile_metadata=routing_resolution.execution_profile_metadata,
    )
    state.agent_mode = await resolve_agent_mode(db, routing_resolution.effective_agent_type)
    await db.commit()  # turn preparation's commit point (see turn_routing_resolution)
    state.capability_type = state.agent_mode.capability_type
    return state


async def load_turn_history(request: AgentRunRequest, state: RunPreparation) -> None:
    """Load the personality, the stored history, the thread context, the user's roles and the tool domains."""
    db, session_id, user_id = request.db, request.session_id, request.user_id
    state.personality = (
        await db.execute(select(Personality).where(Personality.user_id == user_id))
    ).scalar_one_or_none()

    all_history = (
        (await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .limit(_MAX_HISTORY_MESSAGES)
        ))
        .scalars()
        .all()
    )
    session_metadata = state.session_metadata
    state.session_summary = session_metadata.get("summary") if state.current_session else None
    state.session_summary_references = (
        session_metadata.get("summary_references") if state.current_session else None
    )
    current_turn_user_message_id = str(session_metadata.get("current_turn_user_message_id") or "").strip()
    existing_thread_context_row = (
        await db.execute(select(ThreadContext).where(ThreadContext.session_id == session_id))
    ).scalar_one_or_none()
    state.existing_thread_context = (
        dict(existing_thread_context_row.context_json or {})
        if existing_thread_context_row and isinstance(existing_thread_context_row.context_json, dict)
        else {}
    )

    state.all_history, state.current_turn_message = split_current_turn_from_history(
        await exclude_runtime_readiness_blocked_turns(db, session_id=session_id, messages=all_history),
        current_turn_user_message_id,
    )

    role_result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    state.user_roles = [r[0] for r in role_result.all()] or ["viewer"]
    state.tool_domain_config = await get_agent_tool_domain_config(db)
