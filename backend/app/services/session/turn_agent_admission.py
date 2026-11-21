"""The turn's agent, admitted before the automatic workflow proposal.

A turn without an explicit workflow asks the Workspace's workflow proposal (a governed model
call) before the preparation lock (``workflow_routing/proposal_prefetch``). When the user chose
the turn's agent directly, that call is spent on nothing: the agent controls the turn. So the
prefetch first admits the agent the same way preparation does:

* the session under the request's own scope rule (``load_request_turn_session``), the Workspace
  execution view and project membership, the session owner's agents;
* canonical selection precedence (``turn_agent_selection.choose_turn_agent``:
  explicit > exact mention > bound session > Workspace default) with no workflow selected,
  the Workspace allowance and the explicit resolution (unknown, foreign, inactive, unpublished).

Outcomes: a refusal raises ``TurnRefusedError`` (the prefetch makes no call; preparation refuses
the turn with its own state); an admitted agent from a *direct* source skips the proposal
(``direct_agent_selected``); anything else (no agent, Workspace default) keeps the
governed proposal, so a workflow can still exclude an implicit agent.

Preparation revalidates under the lock (:func:`confirm_direct_agent_skip`): the skip stands only
when the final canonical choice is the same agent from the same source; otherwise the record
becomes ``proposal_scope_changed``. Both outcomes select no workflow, so only the recorded reason
changes, and no model call is made under the lock either way.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import User
from ..workflow_routing.proposal import proposal_scope_changed_resolution
from ..workflow_routing.proposal_prefetch import DirectAgentSkip, PrecomputedWorkflowProposal
from ..workflow_routing.proposal_states import WORKFLOW_PROPOSAL_KEY
from .agent_selection_sources import AgentSelectionSource
from .turn_agent_selection import AgentChoice, choose_turn_agent, no_selected_workflow
from .turn_project_scope import turn_workspace_execution_view

# Sources the user chose the agent through; the Workspace default is not.
DIRECT_AGENT_SOURCES = frozenset(
    {AgentSelectionSource.EXPLICIT, AgentSelectionSource.MENTION, AgentSelectionSource.SESSION}
)
DIRECT_AGENT_SELECTED = "direct_agent_selected"


async def admit_agent_before_proposal(
    db: AsyncSession,
    *,
    user: User,
    session: AgentSession | None,
    effective_project_id: str,
    agent_id: str,
    agent_type_explicit: bool,
    clean_prompt: str,
) -> DirectAgentSkip | None:
    """The directly chosen, admitted agent the proposal is skipped for; ``None`` keeps the proposal.

    Raises ``TurnRefusedError`` for a turn preparation will refuse.
    """
    view = await turn_workspace_execution_view(
        db, user_id=user.id, session=session, effective_project_id=effective_project_id
    )
    choice = await choose_turn_agent(
        db,
        # The session owner's agents, as in preparation.
        owner_id=session.user_id if session is not None else user.id,
        agent_id=agent_id,
        agent_type_explicit=agent_type_explicit,
        clean_prompt=clean_prompt,
        session=session,
        excludes_agent_type=no_selected_workflow,
        workspace_execution_view=view,
        project_id=effective_project_id or None,
    )
    if choice.resolution is None or choice.selection_source not in DIRECT_AGENT_SOURCES:
        return None
    return DirectAgentSkip(agent_id=choice.agent_id, source=choice.selection_source.value)


def confirm_direct_agent_skip(
    policy_resolution: dict[str, Any],
    precomputed: PrecomputedWorkflowProposal | None,
    choice: AgentChoice,
) -> None:
    """Keep a ``direct_agent_selected`` skip only for the same agent and source; else scope changed."""
    skipped_for = precomputed.direct_agent if precomputed is not None else None
    record = policy_resolution.get(WORKFLOW_PROPOSAL_KEY)
    if skipped_for is None or not isinstance(record, dict) or record.get("reason_code") != DIRECT_AGENT_SELECTED:
        return
    if choice.resolution is not None and (choice.agent_id, choice.selection_source.value) == (
        skipped_for.agent_id,
        skipped_for.source,
    ):
        return
    policy_resolution.update(proposal_scope_changed_resolution())


__all__ = [
    "DIRECT_AGENT_SELECTED",
    "DIRECT_AGENT_SOURCES",
    "admit_agent_before_proposal",
    "confirm_direct_agent_skip",
]
