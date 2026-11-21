"""Workflow proposals resolved before the chat preparation lock.

Turn preparation runs under the process-global ``TURN_PREPARE_LOCK`` (``session/turn_start``). The
workflow proposal is a governed model call with a budget of up to the admin setting
``workflow_proposal_settings.timeout_seconds``, so it must not run under that lock: a slow provider
would delay every other user's turn.

The lock wrapper therefore resolves the proposal first, in its own short database session, and
hands the result in as a ``PrecomputedWorkflowProposal``. The result is keyed by the effective
Workspace and a hash of the cleaned prompt. Under the lock the selection uses it only when that
key matches the turn; any mismatch (and a prefetch that could not resolve) becomes the explicit
``proposal_scope_changed`` outcome. No proposal model call is ever made under the lock.

The proposal itself is unchanged: same resolver, budget, admission, content policies, record and
``needs_confirmation`` rules. Both entry paths (``/chat/api`` and
``/api/v1``) prepare through ``services/session/turn_start.prepare_turn``, so both prefetch.

Before the call, the turn's agent is admitted the canonical way
(``session/turn_agent_admission``): the request's own session scope, the Workspace, selection
precedence and the explicit resolution. A refused agent makes no call (preparation refuses the
turn); an admitted agent the user chose directly skips the proposal as
``direct_agent_selected``, which preparation keeps only for that same agent.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from ...models import User
from ..access_control import require_project_access
from ..session.turn_project_scope import load_request_turn_session, resolve_turn_project_scope
from ..session.turn_refusals import TurnRefusedError
from ..session.turn_request import SESSION_SCOPE_OWN_OR_NEW
from .proposal import (
    direct_agent_selected_resolution,
    proposal_scope_changed_resolution,
    resolve_workflow_proposal_for_turn,
)

logger = logging.getLogger(__name__)


def proposal_prompt_hash(message: str) -> str:
    """The key of the cleaned prompt a proposal was resolved for."""
    return hashlib.sha256(str(message or "").strip().encode("utf-8")).hexdigest()


def _scope_key(project_id: str | None) -> str:
    return str(project_id or "").strip()


@dataclass(frozen=True, slots=True)
class DirectAgentSkip:
    """The admitted agent a proposal was skipped for, and the selection source that chose it."""

    agent_id: str
    source: str


@dataclass(frozen=True, slots=True)
class PrecomputedWorkflowProposal:
    """A proposal resolved before the preparation lock, with the scope it was resolved for.

    ``resolution`` is ``None`` when the prefetch did not resolve a proposal (the routing mode
    was not ``explicit``, or the turn's scope could not be resolved; preparation then reports
    that turn's own error). Such a prefetch still forbids a model call under the lock.
    ``direct_agent`` is set when the proposal was skipped for a directly chosen agent.
    """

    project_id: str
    prompt_hash: str
    resolution: dict[str, Any] | None
    direct_agent: DirectAgentSkip | None = None

    def resolution_for_turn(self, *, user_message: str, project_id: str | None) -> dict[str, Any]:
        """The precomputed resolution when the key matches; else ``proposal_scope_changed``."""
        if (
            self.resolution is not None
            and self.project_id == _scope_key(project_id)
            and self.prompt_hash == proposal_prompt_hash(user_message)
        ):
            # A copy: preparation may retry, and each attempt persists its own metadata.
            return copy.deepcopy(self.resolution)
        logger.info("workflow_proposal.scope_changed")
        return proposal_scope_changed_resolution()


async def _resolve_before_lock(
    db,
    *,
    user_id: str,
    prompt: str,
    session_id: str,
    session_scope: str,
    project_id: str,
    agent_id: str,
    agent_type_explicit: bool,
) -> tuple[dict[str, Any] | None, str, DirectAgentSkip | None]:
    from ..session.turn_agent_admission import admit_agent_before_proposal

    user = await db.get(User, user_id)
    if user is None:
        return None, _scope_key(project_id), None
    session = await load_request_turn_session(
        db, user_id=user.id, session_id=session_id, session_scope=session_scope
    )
    _project_id, effective_project_id = await resolve_turn_project_scope(
        db, user=user, project_id=project_id, session=session
    )
    if effective_project_id:
        # Preparation rejects this turn anyway; no model call for a Workspace the user cannot use.
        await require_project_access(db, user.id, effective_project_id)
    # Raises TurnRefusedError for an agent preparation will refuse: no model call for it either.
    direct_agent = await admit_agent_before_proposal(
        db,
        user=user,
        session=session,
        effective_project_id=effective_project_id,
        agent_id=agent_id,
        agent_type_explicit=agent_type_explicit,
        clean_prompt=prompt,
    )
    if direct_agent is not None:
        logger.info("workflow_proposal.skipped", extra={"reason_code": "direct_agent_selected"})
        return direct_agent_selected_resolution(), effective_project_id, direct_agent
    resolution = await resolve_workflow_proposal_for_turn(
        db, user_message=prompt, project_id=effective_project_id or None
    )
    return resolution, effective_project_id, None


async def prefetch_workflow_proposal(
    session_factory,
    *,
    user_id: str,
    prompt: str,
    session_id: str = "",
    session_scope: str = SESSION_SCOPE_OWN_OR_NEW,
    project_id: str = "",
    workflow_key: str = "",
    agent_id: str = "",
    agent_type_explicit: bool = False,
) -> PrecomputedWorkflowProposal | None:
    """Resolve the turn's workflow proposal outside the preparation lock.

    ``None`` only for an explicit ``workflow_key`` (including ``WORKFLOW_KEY_NONE``): that turn
    never makes a proposal call. Every other turn gets a ``PrecomputedWorkflowProposal``.
    """
    if str(workflow_key or "").strip():
        return None
    clean_prompt = str(prompt or "").strip()
    resolution: dict[str, Any] | None = None
    direct_agent: DirectAgentSkip | None = None
    scope = _scope_key(project_id)
    async with session_factory() as db:
        if clean_prompt:
            try:
                resolution, scope, direct_agent = await _resolve_before_lock(
                    db,
                    user_id=user_id,
                    prompt=clean_prompt,
                    session_id=session_id,
                    session_scope=session_scope,
                    project_id=project_id,
                    agent_id=agent_id,
                    agent_type_explicit=agent_type_explicit,
                )
            except (TurnRefusedError, HTTPException):
                # Preparation under the lock refuses the same turn with its own state.
                resolution = None
        # Persist what the proposal recorded, as preparation's own commit did before.
        await db.commit()
    return PrecomputedWorkflowProposal(
        project_id=scope,
        prompt_hash=proposal_prompt_hash(clean_prompt),
        resolution=resolution,
        direct_agent=direct_agent,
    )


__all__ = ["DirectAgentSkip", "PrecomputedWorkflowProposal", "prefetch_workflow_proposal", "proposal_prompt_hash"]
