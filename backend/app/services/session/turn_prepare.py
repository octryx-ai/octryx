"""Prepare one turn inside a database session: the single preparation owner of both entry paths.

:func:`prepare_turn_in_session` decides, in this order, and refuses with ``TurnRefusedError``:

1. the prompt (``prompt_required``), the runtime the caller named (``runtime_target_invalid``);
2. the session: the caller's own or a new one (``/chat/api``), or the existing writable one
   (``/api/v1``: ``session_not_found`` / ``session_access_denied``); the Workspace scope
   (``project_*``);
3. routing and execution strategy (``turn_routing_resolution``), the Workspace execution view
   and project membership (``project_not_found``, the same as an unknown Workspace), the runtime
   (``turn_runtime_selection``, ``runtime_not_allowed``) and the agent (``turn_agent_selection``, ``agent_*``);
4. the execution profile, always built, and the session record (``turn_session_record``:
   ``session_archived``, ``turn_already_running``, ``duplicate_text``), committed with the turn
   marker.

Locking, the SQLite retry and the workflow proposal before the lock are ``turn_start``'s.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..agent_mode import DEFAULT_AGENT_MODE_KEY
from ..clarification_service import answer_open_clarification_with_reply
from ..execution_profile_service import build_execution_profile
from ..platform_agents.catalog import agent_mode_of
from ..policy_lists.live import refresh_live_policy_lists
from ..workflow_routing.proposal_prefetch import PrecomputedWorkflowProposal
from .turn_agent_admission import confirm_direct_agent_skip
from .turn_agent_selection import select_turn_agent
from .turn_preparation import resolve_thinking_level
from .turn_project_scope import (
    load_request_turn_session,
    require_project_member,
    resolve_turn_project_scope,
    turn_workspace_execution_view,
)
from .turn_refusals import TurnRefusalState, TurnRefusedError
from .turn_request import PreparedTurn, TurnRequest
from .turn_routing_resolution import resolve_turn_routing, selected_workflow_contract
from .turn_runtime_selection import (
    initial_runtime_choice,
    require_runtime_allowed,
    resolve_turn_runtime,
)
from .turn_session_record import TurnFacts, record_prepared_turn


async def prepare_turn_in_session(
    db: AsyncSession,
    *,
    user: User,
    request: TurnRequest,
    precomputed_proposal: PrecomputedWorkflowProposal | None = None,
) -> PreparedTurn:
    clean_prompt = str(request.prompt or "").strip()
    if not clean_prompt:
        raise TurnRefusedError(TurnRefusalState.PROMPT_REQUIRED, "Prompt is required")
    # Admin-edited policy lists (capabilities, weak families, diagram options) are live from here on.
    await refresh_live_policy_lists(db)
    runtime = await initial_runtime_choice(
        db, runtime_target_id=request.runtime_target_id, runtime_target_id_explicit=request.runtime_target_id_explicit
    )
    thinking_level = resolve_thinking_level(request.thinking_level)
    session = await load_request_turn_session(
        db, user_id=user.id, session_id=request.session_id, session_scope=request.session_scope
    )
    # An empty agent type is the session's (``/api/v1`` sends none); ``/chat/api`` always sends one.
    requested_agent_type = (
        str(request.agent_type or (session.agent_type if session else "") or "").strip() or DEFAULT_AGENT_MODE_KEY
    )
    # The session owner's agents: for ``/chat/api`` always the caller.
    agent_owner_id = session.user_id if session is not None else user.id
    project_id, effective_project_id = await resolve_turn_project_scope(
        db, user=user, project_id=request.project_id, session=session
    )
    routing = await resolve_turn_routing(
        db,
        clean_prompt=clean_prompt,
        session=session,
        requested_agent_type=requested_agent_type,
        agent_type_explicit=request.agent_type_explicit,
        project_id=project_id,
        effective_project_id=effective_project_id,
        agent_id=request.agent_id,
        # An agent brings no default workflow; the request's explicit key is the only one.
        workflow_key=request.workflow_key.strip(),
        precomputed_proposal=precomputed_proposal,
        platform_workflow_service=request.platform_workflow_service,
        workflow_decisions=request.workflow_decisions,
    )
    view = await turn_workspace_execution_view(
        db, user_id=user.id, session=session, effective_project_id=effective_project_id
    )
    if request.runtime_target_id_explicit and runtime.runtime_target_id:
        require_runtime_allowed(view, runtime_target_id=runtime.runtime_target_id)
    agent = await select_turn_agent(
        db,
        owner_id=agent_owner_id,
        agent_id=request.agent_id,
        agent_type_explicit=request.agent_type_explicit,
        clean_prompt=clean_prompt,
        session=session,
        routing=routing,
        workspace_execution_view=view,
        project_id=effective_project_id or None,
    )
    # A proposal skipped for a direct agent stays skipped only for that same agent.
    confirm_direct_agent_skip(routing.policy_resolution, precomputed_proposal, agent)
    if agent.resolution is not None:
        if not request.project_id_explicit and not project_id and agent.resolution.project_id:
            project_id = agent.resolution.project_id
            await require_project_member(db, user_id=user.id, project_id=project_id)
        agent_thinking_level = agent.resolution.thinking_level
        if not request.thinking_level_explicit and request.thinking_level == "light" and agent_thinking_level:
            thinking_level = agent_thinking_level
    await resolve_turn_runtime(
        db,
        runtime,
        runtime_target_id_explicit=request.runtime_target_id_explicit,
        session=session,
        workspace_execution_view=view,
        agent_runtime_target_id=agent.resolution.runtime_target_id if agent.resolution is not None else None,
        workflow_contract=selected_workflow_contract(routing.policy_resolution),
    )
    session_agent_type = (
        routing.selected_mode_key
        if request.agent_type_explicit
        else ((agent_mode_of(agent.payload) if agent.resolution else "") or routing.selected_mode_key)
    )
    decision = routing.strategy_decision
    execution_profile = build_execution_profile(
        prompt=clean_prompt,
        requested_agent_type=requested_agent_type,
        effective_agent_type=session_agent_type,
        execution_strategy=routing.execution_strategy,
        execution_strategy_reason=routing.execution_strategy_reason,
        routing_intent=routing.routing_intent,
        routing_reason=routing.routing_reason,
        routing_intent_confidence=decision.routing_intent_confidence,
        routing_intent_source=decision.routing_intent_source,
        workflow_id=routing.expected_workflow_id,
        workflow_contract=decision.workflow_contract,
        agent_type_explicit=request.agent_type_explicit,
        workflow_routing_policy_resolution=routing.policy_resolution,
        runtime_target_id=runtime.runtime_target_id or None,
        runtime_label=runtime.runtime_label,
    ).to_metadata()
    facts = TurnFacts(
        clean_prompt=clean_prompt,
        project_id=project_id,
        session_agent_type=session_agent_type,
        thinking_level=thinking_level,
        runtime=runtime,
        routing=routing,
        agent=agent,
        execution_profile=execution_profile,
        workspace_execution_view=view,
    )
    session, user_message = await record_prepared_turn(
        db,
        user_id=user.id,
        session=session,
        facts=facts,
        idempotency_key=request.idempotency_key,
        workflow_key=request.workflow_key,
        workflow_decisions=request.workflow_decisions,
        session_metadata_patch=request.session_metadata_patch,
    )
    # A reply in the thread answers the session's open clarification.
    await answer_open_clarification_with_reply(db, session_id=session.id, answered_by=user.id, reply=clean_prompt)
    return PreparedTurn(
        session_id=session.id,
        user_message_id=user_message.id,
        prompt=clean_prompt,
        project_id=session.project_id,
        agent_type=session.agent_type,
        runtime_target_id=runtime.runtime_target_id or None,
        thinking_level=thinking_level,
        agent_definition=agent.payload,
    )


__all__ = [
    "prepare_turn_in_session",
]
