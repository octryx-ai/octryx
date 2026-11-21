"""Resume what a decided session approval paused: one owner for every decision route.

Every route that decides a session approval (``/chat/api/approvals``, the admin
panel, ``/api/v1/approvals``, channel approval commands) hands the decided approval to
:func:`resume_decided_approval` (through ``approval_decision``). It resumes:

* a **workflow proposal** held by the execution gate: approved re-sends the held
  message once with the proposed workflow, rejected without a workflow
  (``workflow_routing/proposal_approval``);
* a **native chat turn** paused at a tool approval: approved with a change
  preview grant, the turn restarts through ``turn_launch.launch_chat_turn``;
  rejected, the turn restarts with a fixed rejection note.

Every resume runs as the paused turn's owner (the approval's requester), never as
the decider. Which turn to resume is consumed once (``turn_approval_state``); an
approval without a resumable turn logs an explicit ``TurnNotResumable`` reason.
The function commits.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...db import core as db_core
from ...models import Approval, User
from ...models import Session as AgentSession
from ...time_utils import utc_now
from ..prompt_catalog import prompt_set_scope, render_prompt
from ..prompt_catalog.out_of_turn import prompt_set_for
from ..workflow_routing.proposal_approval import resume_workflow_proposal_approval
from .run_state import (
    RUN_STATUS_IN_PROGRESS,
    set_session_run_state,
)
from .turn_approval_state import PausedTurn, TurnNotResumable, begin_chat_turn, take_paused_turn
from .turn_launch import launch_chat_turn, resolve_turn_agent_definition

logger = logging.getLogger(__name__)

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"

NOT_RESUMABLE_OWNER_MISSING = "owner_missing"
NOT_RESUMABLE_NO_GRANTS = "approval_has_no_grants"
NOT_RESUMABLE_DECISION = "decision_not_resumable"


def _log_not_resumable(session: AgentSession, outcome: TurnNotResumable) -> None:
    logger.warning(
        "chat.turn.approval_resume.not_resumable",
        extra={"session_id": session.id, "approval_id": outcome.approval_id, "reason": outcome.reason},
    )


async def _not_resumable(db: AsyncSession, session: AgentSession, approval_id: str, reason: str) -> None:
    _log_not_resumable(session, TurnNotResumable(approval_id=approval_id, reason=reason))
    await db.commit()


async def _restart_paused_chat_turn(
    db: AsyncSession,
    *,
    session: AgentSession,
    paused_turn: PausedTurn,
    session_factory,
    resume_state: str,
    prompt_override: str | None = None,
) -> None:
    """Restart the paused turn as its owner, never as the decider."""
    owner = await db.get(User, paused_turn.owner_user_id) if paused_turn.owner_user_id else None
    if owner is None:
        await _not_resumable(db, session, paused_turn.approval_id, NOT_RESUMABLE_OWNER_MISSING)
        return
    metadata = dict(session.metadata_ or {})
    selected_agent_payload = await resolve_turn_agent_definition(db, metadata, owner_id=owner.id)

    session.status = "running"
    session.ended_at = None
    turn_started_at = utc_now()
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    metadata["resume_state"] = resume_state
    begin_chat_turn(metadata, user_message_id=paused_turn.user_message_id, started_at=turn_started_at)
    metadata.setdefault("run_started_at", turn_started_at.isoformat())
    session.metadata_ = metadata
    await db.commit()

    launch_chat_turn(
        session_factory=session_factory,
        session_id=session.id,
        user_id=owner.id,
        prompt=str(prompt_override or paused_turn.prompt),
        project_id=session.project_id,
        agent_type=session.agent_type,
        runtime_target_id=str(metadata.get("runtime_target_id") or "").strip() or None,
        thinking_level=str(metadata.get("thinking_level") or "light").strip() or "light",
        agent_definition=selected_agent_payload,
    )


async def _resume_approved_chat_turn(
    db: AsyncSession, *, session: AgentSession, approval: Approval, session_factory
) -> None:
    paused_turn = await take_paused_turn(db, session, approval_id=approval.id)
    metadata = dict(session.metadata_ or {})
    preview_grants = [
        grant for grant in metadata.get("approval_grants") or []
        if grant.get("approval_id") == approval.id and str(grant.get("request_fingerprint") or "").strip()
    ]
    if not preview_grants:
        await _not_resumable(db, session, approval.id, NOT_RESUMABLE_NO_GRANTS)
        return
    if isinstance(paused_turn, TurnNotResumable):
        _log_not_resumable(session, paused_turn)
        await db.commit()
        return
    await _restart_paused_chat_turn(
        db,
        session=session,
        paused_turn=paused_turn,
        session_factory=session_factory,
        resume_state="approval_approved",
    )


async def _resume_rejected_chat_turn(
    db: AsyncSession, *, session: AgentSession, approval: Approval, session_factory
) -> None:
    paused_turn = await take_paused_turn(db, session, approval_id=approval.id)
    if isinstance(paused_turn, TurnNotResumable):
        _log_not_resumable(session, paused_turn)
        await db.commit()
        return
    # An approval decision runs outside a turn: render for the session's Workspace.
    with prompt_set_scope(await prompt_set_for(db, workspace_id=getattr(session, "project_id", None))):
        rejection_reason = str(approval.reason or "").strip() or render_prompt(
            "secure_work.approval.default_rejection_reason"
        )
        action = str(approval.action or "").strip()
        resume_prompt = render_prompt(
            "secure_work.approval.rejected_resume",
            original_prompt=paused_turn.prompt,
            action=action or render_prompt("secure_work.approval.default_action"),
            rejection_reason=rejection_reason,
        )
    await _restart_paused_chat_turn(
        db,
        session=session,
        paused_turn=paused_turn,
        session_factory=session_factory,
        prompt_override=resume_prompt,
        resume_state="approval_rejected",
    )


async def resume_decided_approval(
    db: AsyncSession,
    *,
    session: AgentSession,
    approval: Approval,
    decision: str,
    session_factory=None,
) -> None:
    """Resume the turn ``approval`` paused, per ``decision``; commits."""
    factory = session_factory or db_core.async_session_factory
    if await resume_workflow_proposal_approval(
        db, session=session, approval=approval, decision=decision, session_factory=factory
    ):
        return
    if decision == DECISION_APPROVED:
        await _resume_approved_chat_turn(db, session=session, approval=approval, session_factory=factory)
    elif decision == DECISION_REJECTED:
        await _resume_rejected_chat_turn(db, session=session, approval=approval, session_factory=factory)
    else:
        await _not_resumable(db, session, approval.id, NOT_RESUMABLE_DECISION)


__all__ = [
    "DECISION_APPROVED",
    "DECISION_REJECTED",
    "resume_decided_approval",
]
