"""The Agent Definition a turn runs with, and the one source it came from.

Precedence, first match wins (``AgentSelectionSource``):

0. ``workflow_phase``: inside a workflow run the phase's agent; no pick applies;
1. ``explicit``: the caller's ``agent_id``;
2. ``mention``: an exact ``@<configured name>`` mention of one of the owner's agents
   (``turn_agent_mention``; conflicting mentions are ``agent_mention_ambiguous``). It
   overrides the session's bound agent for this turn only (``bound_agent_after_turn``);
3. ``session``: the agent the session is bound to, unless the caller chose an agent type
   this turn or the turn's workflow definition excludes the session's agent type
   (:func:`workflow_excludes_agent_type`);
4. ``default``: the Workspace composition's default agent binding, when no
   agent type was chosen and the workflow definition does not exclude it;
5. ``platform_default``: the platform Assistant: there is no anonymous turn.
   An Assistant that cannot run refuses the turn ``agent_definition_refused``.

The platform agents are global and never need a Workspace binding, so ``selected_only`` does
not refuse them.

No source reads the prompt beyond the exact mention: there is no keyword, capability or
metadata scoring. The chosen definition is resolved explicitly: an unknown one is
``agent_not_found``, an inactive, unpublished or misconfigured one
``agent_definition_refused``, one outside a ``selected_only`` Workspace ``agent_not_allowed``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import REFUSAL_STATUSES, STATUS_NOT_FOUND, AgentDefinitionResolution
from app.services.execution_strategy_intent import ROUTING_INTENT_SOURCE_POLICY

from ...models import Session as AgentSession
from ...models import Task
from ..agent_definition_execution import resolve_agent_definition_for_execution
from ..agent_definition_execution_outcomes import execution_refusal_detail
from ..agent_mode import DEFAULT_AGENT_MODE_KEY
from ..workspace_composition.assignment_policy import (
    AGENT_NOT_ALLOWED_DETAIL,
    default_agent_binding,
    is_agent_allowed,
)
from .agent_selection_sources import AgentSelectionSource, session_bound_agent_id
from .turn_agent_mention import resolve_mentioned_agent_id
from .turn_refusals import TurnRefusalState, TurnRefusedError
from .turn_routing_resolution import TurnRouting

# A workflow definition routing to one of these intents is a read-only investigation...
_READ_ONLY_ROUTING_INTENTS = frozenset({"diagnosis", "operations"})
# ...which only these agent types serve; a delivery agent is never carried into it.
_READ_ONLY_AGENT_TYPES = frozenset({"", DEFAULT_AGENT_MODE_KEY, "chat", "diagnosis", "operations", "sre"})


@dataclass(slots=True)
class AgentChoice:
    agent_id: str
    selection_source: AgentSelectionSource
    resolution: AgentDefinitionResolution | None
    payload: dict[str, Any] | None


def workflow_excludes_agent_type(routing: TurnRouting, agent_type: str) -> bool:
    """Whether the turn's workflow definition rules out an implicit agent of ``agent_type``.

    Only a policy-sourced routing intent (a selected workflow definition) counts; the
    diagnosis default of a turn without a workflow never excludes an agent.
    """
    if routing.strategy_decision.routing_intent_source != ROUTING_INTENT_SOURCE_POLICY:
        return False
    if str(routing.routing_intent or "").strip().lower() not in _READ_ONLY_ROUTING_INTENTS:
        return False
    return str(agent_type or "").strip().lower() not in _READ_ONLY_AGENT_TYPES


async def _session_agent_id(db: AsyncSession, session: AgentSession) -> str:
    metadata = dict(session.metadata_ or {})
    agent_id = session_bound_agent_id(metadata)
    if agent_id:
        return agent_id
    task_id = str(metadata.get("task_id") or "").strip()
    task = await db.get(Task, task_id) if task_id else None
    return str((task.config or {}).get("agent_definition_id") or "").strip() if task else ""


# Whether the turn's workflow rules out an implicit agent of the given type.
ExcludesAgentType = Callable[[str], bool]


def no_selected_workflow(_agent_type: str) -> bool:
    """No workflow is selected, so none excludes an implicit agent (the admission before a proposal)."""
    return False


def _workspace_default_agent_id(
    workspace_execution_view: dict | None, *, excludes_agent_type: ExcludesAgentType
) -> str:
    binding = default_agent_binding(workspace_execution_view)
    if binding is None or excludes_agent_type(str(binding.get("agent_type") or "")):
        return ""
    return str(binding.get("source_entity_id") or "").strip()


async def _select_agent_id(
    db: AsyncSession,
    *,
    owner_id: str,
    agent_id: str,
    agent_type_explicit: bool,
    clean_prompt: str,
    session: AgentSession | None,
    excludes_agent_type: ExcludesAgentType,
    workspace_execution_view: dict | None,
    project_id: str | None,
) -> tuple[str, AgentSelectionSource]:
    if agent_id:
        return agent_id, AgentSelectionSource.EXPLICIT
    mentioned_id = await resolve_mentioned_agent_id(db, owner_id=owner_id, prompt=clean_prompt, project_id=project_id)
    if mentioned_id:
        return mentioned_id, AgentSelectionSource.MENTION
    session_reusable = session is not None and not agent_type_explicit
    if session_reusable and not excludes_agent_type(session.agent_type):
        session_agent_id = await _session_agent_id(db, session)
        if session_agent_id:
            return session_agent_id, AgentSelectionSource.SESSION
    if not agent_type_explicit:
        default_id = _workspace_default_agent_id(workspace_execution_view, excludes_agent_type=excludes_agent_type)
        if default_id:
            return default_id, AgentSelectionSource.DEFAULT
    return "", AgentSelectionSource.NONE


async def resolve_turn_agent_definition(
    db: AsyncSession, *, agent_id: str, owner_id: str, project_id: str | None = None
) -> tuple[AgentDefinitionResolution, dict[str, Any]]:
    resolution = await resolve_agent_definition_for_execution(
        db, definition_id=agent_id, visible_to_user_id=owner_id, workspace_id=project_id
    )
    if resolution.status in REFUSAL_STATUSES:
        raise TurnRefusedError(TurnRefusalState.AGENT_DEFINITION_REFUSED, execution_refusal_detail(resolution))
    if resolution.status == STATUS_NOT_FOUND or resolution.payload is None:
        raise TurnRefusedError(TurnRefusalState.AGENT_NOT_FOUND, "Agent not found")
    return resolution, resolution.payload


async def choose_turn_agent(
    db: AsyncSession,
    *,
    owner_id: str,
    agent_id: str,
    agent_type_explicit: bool,
    clean_prompt: str,
    session: AgentSession | None,
    excludes_agent_type: ExcludesAgentType,
    workspace_execution_view: dict | None,
    project_id: str | None = None,
) -> AgentChoice:
    """The canonical choice: precedence, Workspace allowance and the explicit resolution.

    *project_id* is the turn's Workspace: when set, only global, built-in and its own agents can run.
    """
    effective_agent_id, source = await _select_agent_id(
        db,
        owner_id=owner_id,
        agent_id=str(agent_id or "").strip(),
        agent_type_explicit=agent_type_explicit,
        clean_prompt=clean_prompt,
        session=session,
        excludes_agent_type=excludes_agent_type,
        workspace_execution_view=workspace_execution_view,
        project_id=project_id,
    )
    from .platform_default_agent import is_platform_agent_id, platform_default_agent_id

    if not effective_agent_id:
        effective_agent_id, source = await platform_default_agent_id(db), AgentSelectionSource.PLATFORM_DEFAULT
    if source != AgentSelectionSource.PLATFORM_DEFAULT and not (
        is_agent_allowed(workspace_execution_view, agent_id=effective_agent_id)
        or await is_platform_agent_id(db, effective_agent_id)
    ):
        raise TurnRefusedError(TurnRefusalState.AGENT_NOT_ALLOWED, AGENT_NOT_ALLOWED_DETAIL)
    resolution, payload = await resolve_turn_agent_definition(
        db, agent_id=effective_agent_id, owner_id=owner_id, project_id=project_id
    )
    return AgentChoice(agent_id=effective_agent_id, selection_source=source, resolution=resolution, payload=payload)


async def select_turn_agent(
    db: AsyncSession,
    *,
    owner_id: str,
    agent_id: str,
    agent_type_explicit: bool,
    clean_prompt: str,
    session: AgentSession | None,
    routing: TurnRouting,
    workspace_execution_view: dict | None,
    project_id: str | None = None,
) -> AgentChoice:
    """The turn's agent: a workflow phase's bound agent, else the canonical choice."""
    from ..workflow_runs.phase_agent_binding import phase_agent_of

    phase_agent = phase_agent_of(routing.policy_resolution)
    if phase_agent is not None:
        resolution, payload = await resolve_turn_agent_definition(
            db, agent_id=phase_agent["definition_id"], owner_id=owner_id, project_id=project_id)
        return AgentChoice(agent_id=phase_agent["definition_id"], selection_source=AgentSelectionSource.WORKFLOW_PHASE,
                           resolution=resolution, payload=payload)
    return await choose_turn_agent(
        db,
        owner_id=owner_id,
        agent_id=agent_id,
        agent_type_explicit=agent_type_explicit,
        clean_prompt=clean_prompt,
        session=session,
        excludes_agent_type=lambda agent_type: workflow_excludes_agent_type(routing, agent_type),
        workspace_execution_view=workspace_execution_view,
        project_id=project_id,
    )


__all__ = [
    "AgentChoice",
    "ExcludesAgentType",
    "choose_turn_agent",
    "no_selected_workflow",
    "resolve_turn_agent_definition",
    "select_turn_agent",
    "workflow_excludes_agent_type",
]
