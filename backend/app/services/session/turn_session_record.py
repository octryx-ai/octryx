"""The last step of turn preparation: persist the prepared facts and mark the turn."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import RESOLUTION_METADATA_KEY

from ...models import Message
from ...models import Session as AgentSession
from ...time_utils import utc_now
from ..agent_definition_execution_outcomes import resolution_metadata
from ..double_text_guard_service import DoubleTextGuardError, check_double_text_guard
from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from .agent_selection_sources import (
    AGENT_SELECTION_SOURCE_METADATA_KEY,
    BOUND_AGENT_METADATA_KEY,
    bound_agent_after_turn,
    session_bound_agent_id,
)
from .run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from .session_title import TITLE_SOURCE_KEY, apply_prompt_title, title_from_prompt
from .turn_agent_selection import AgentChoice
from .turn_approval_state import begin_chat_turn
from .turn_preparation import clear_stale_workflow_metadata
from .turn_refusals import TurnRefusalState, TurnRefusedError
from .turn_routing_resolution import TurnRouting
from .turn_runtime_selection import RUNTIME_SELECTION_SOURCE_METADATA_KEY, RuntimeChoice
from .turn_selection import record_turn_selection
from .turn_tasks import effective_session_status
from .workspace import ensure_session_workspace_root


@dataclass(frozen=True, slots=True)
class TurnFacts:
    clean_prompt: str
    project_id: str
    session_agent_type: str
    thinking_level: str
    runtime: RuntimeChoice
    routing: TurnRouting
    agent: AgentChoice
    execution_profile: dict[str, Any]
    workspace_execution_view: dict | None


def _turn_metadata(facts: TurnFacts) -> dict[str, Any]:
    resolution = facts.agent.resolution
    decision = facts.routing.strategy_decision
    return {
        "runtime_target_id": facts.runtime.runtime_target_id or None,
        "runtime_label": facts.runtime.runtime_label,
        RUNTIME_SELECTION_SOURCE_METADATA_KEY: facts.runtime.source.value,
        "thinking_level": facts.thinking_level,
        "agent_definition_id": resolution.definition_id if resolution else None,
        "agent_name": (facts.agent.payload or {}).get("name") if resolution else None,
        # The platform agent's key and revision, so history shows who ran (and in which version).
        "agent_key": (facts.agent.payload or {}).get("builtinKey") or None if resolution else None,
        "agent_revision": getattr(resolution, "revision_number", None) if resolution else None,
        # The executed source is canonical session state, not just a key on the payload.
        RESOLUTION_METADATA_KEY: resolution_metadata(resolution)[RESOLUTION_METADATA_KEY] if resolution else None,
        AGENT_SELECTION_SOURCE_METADATA_KEY: facts.agent.selection_source.value,
        "routing_intent": facts.routing.routing_intent,
        "routing_reason": facts.routing.routing_reason,
        "routing_intent_confidence": decision.routing_intent_confidence,
        "routing_intent_source": decision.routing_intent_source,
        "execution_strategy": facts.routing.execution_strategy,
        "execution_strategy_reason": facts.routing.execution_strategy_reason,
        "expected_workflow_id": facts.routing.expected_workflow_id or None,
        "execution_profile": facts.execution_profile,
        ROUTING_RESOLUTION_KEY: facts.routing.policy_resolution,
        "workspace_execution_view": facts.workspace_execution_view,
    }


def _bound_agent(facts: TurnFacts, *, previously_bound: str) -> str | None:
    resolution = facts.agent.resolution
    return bound_agent_after_turn(
        previously_bound=previously_bound,
        source=facts.agent.selection_source,
        turn_agent_id=resolution.definition_id if resolution else "",
    )


async def _create_session(db: AsyncSession, *, user_id: str, facts: TurnFacts) -> AgentSession:
    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=facts.project_id or None,
        agent_type=facts.session_agent_type,
        status="active",
        origin="chat",
        metadata_={
            "title": title_from_prompt(facts.clean_prompt),
            TITLE_SOURCE_KEY: "prompt",
            **_turn_metadata(facts),
            BOUND_AGENT_METADATA_KEY: _bound_agent(facts, previously_bound=""),
        },
    )
    db.add(session)
    await db.flush()
    await ensure_session_workspace_root(db, session)
    return session


async def _update_session(db: AsyncSession, session: AgentSession, *, facts: TurnFacts) -> None:
    status = effective_session_status(session)
    if status == "archived":
        raise TurnRefusedError(
            TurnRefusalState.SESSION_ARCHIVED, "Archived: restore it from Archived chats in the list"
        )
    if status == "running":
        raise TurnRefusedError(TurnRefusalState.TURN_ALREADY_RUNNING, "This thread is already running")
    try:
        await check_double_text_guard(db, session)
    except DoubleTextGuardError:
        raise TurnRefusedError(TurnRefusalState.DUPLICATE_TEXT, "A turn of this thread is still in progress") from None
    metadata = dict(session.metadata_ or {})
    apply_prompt_title(metadata, facts.clean_prompt)
    previously_bound = session_bound_agent_id(metadata)
    metadata.update(_turn_metadata(facts))
    metadata[BOUND_AGENT_METADATA_KEY] = _bound_agent(facts, previously_bound=previously_bound)
    # Stale keys an older turn may have written; nothing reads them
    # (the agent choice is ``agent_selection_source``).
    metadata.pop("safety_plan", None)
    metadata.pop("knowledge_prefetch", None)
    metadata.pop("auto_selected_agent_reason", None)
    clear_stale_workflow_metadata(metadata, expected_workflow_id=facts.routing.expected_workflow_id)
    metadata.pop("completion_blocker", None)
    metadata.pop("last_stop_reason", None)
    session.metadata_ = metadata
    session.project_id = facts.project_id or session.project_id or None
    session.agent_type = facts.session_agent_type
    await ensure_session_workspace_root(db, session)


async def record_prepared_turn(
    db: AsyncSession,
    *,
    user_id: str,
    session: AgentSession | None,
    facts: TurnFacts,
    idempotency_key: str | None,
    workflow_key: str,
    workflow_decisions: dict[str, str] | None,
    session_metadata_patch: dict[str, Any] | None,
) -> tuple[AgentSession, Message]:
    if session is None:
        session = await _create_session(db, user_id=user_id, facts=facts)
    else:
        await _update_session(db, session, facts=facts)
    turn_started_at = utc_now()
    session.last_activity_at = turn_started_at
    session.status = "running"
    session.ended_at = None
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    user_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content=facts.clean_prompt,
        created_at=turn_started_at,
        idempotency_key=idempotency_key,
        author_user_id=user_id,
    )
    db.add(user_message)
    metadata = dict(session.metadata_ or {})
    begin_chat_turn(metadata, user_message_id=user_message.id, started_at=turn_started_at)
    metadata.setdefault("run_started_at", turn_started_at.isoformat())
    if session_metadata_patch:
        metadata.update(session_metadata_patch)
    record_turn_selection(metadata, workflow_key=workflow_key, workflow_decisions=workflow_decisions)
    session.metadata_ = metadata
    await db.commit()
    return session, user_message


__all__ = ["TurnFacts", "record_prepared_turn"]
