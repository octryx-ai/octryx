"""Channel approval commands: ``approve <id>`` and ``reject <id> [reason]``.

The decider is the platform user the sender resolves to (``sender_identity.py``); a sender that
resolves to nobody is refused (``channel_sender_unresolved``) and never decides as the channel's
service user (``run_as.py``). The decision goes through the same owners as every route: a session approval
through ``decide_session_approval`` (write access to its session), any other approval (task
run, governance review) through ``decide_sessionless_approval`` (``services/approval/access.py``).
A refusal is a fixed reply; the HTTP detail is never echoed into the channel.
"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException
from sqlalchemy import select

from ...models.agent.approval import Approval
from ..approval.access import decide_sessionless_approval, require_sessionless_approval_access
from ..session.approval_decision import decide_session_approval
from ..session.turn_approval_state import require_approval_decision_access
from .sender_identity import STATE_SENDER_UNRESOLVED

logger = logging.getLogger(__name__)

# Pattern: "approve <id>" or "reject <id> [reason]"
APPROVE_RE = re.compile(r"^\s*approve\s+([0-9a-f\-]{8,})\s*$", re.IGNORECASE)
REJECT_RE = re.compile(r"^\s*reject\s+([0-9a-f\-]{8,})(?:\s+(.+))?\s*$", re.IGNORECASE)
SENDER_UNRESOLVED_REPLY = (
    f"{STATE_SENDER_UNRESOLVED}: this sender is not linked to a platform user, so it cannot decide approvals."
)


def is_approval_command(content: str) -> bool:
    return bool(APPROVE_RE.match(content) or REJECT_RE.match(content))


async def handle_approval_command(
    db, content: str, sender_user_id: str | None, *, session_factory
) -> str | None:
    """The reply to an approval command, or ``None`` when ``content`` is not one."""
    match = APPROVE_RE.match(content)
    decision, reason = ("approved", None) if match else (None, None)
    if not match:
        match = REJECT_RE.match(content)
        if match:
            decision, reason = "rejected", (match.group(2) or "").strip() or None
    if not match:
        return None
    if not sender_user_id:
        logger.info("channel.approval.refused", extra={"reason": STATE_SENDER_UNRESOLVED})
        return SENDER_UNRESOLVED_REPLY
    return await _decide(db, match.group(1), sender_user_id, decision, reason, session_factory=session_factory)


async def _decide(db, approval_id: str, user_id: str, decision: str, reason: str | None, *, session_factory) -> str:
    short_id = f"{approval_id[:8]}…"
    approval = (await db.execute(select(Approval).where(Approval.id == approval_id))).scalar_one_or_none()
    if not approval:
        return f"Approval {short_id} not found."
    try:
        # Who may decide comes first, so a stranger learns nothing about the approval's state.
        if approval.session_id:
            await require_approval_decision_access(db, approval=approval, user_id=user_id)
        else:
            await require_sessionless_approval_access(db, approval=approval, user_id=user_id)
        if approval.status != "pending":
            return f"Approval {short_id} is already {approval.status}."
        if approval.session_id:
            approval = await decide_session_approval(
                db,
                approval_id=approval_id,
                decider_id=user_id,
                decision=decision,
                reason=reason,
                session_factory=session_factory,
            )
        else:
            approval = await decide_sessionless_approval(
                db, approval=approval, decider_id=user_id, decision=decision, reason=reason
            )
    except HTTPException as exc:
        return _refusal(short_id, exc)
    logger.info("Approval %s %s via channel by user %s", approval_id, decision, user_id)
    if decision == "approved":
        return f"✓ Approved: {approval.action}" + await _start_line(db, approval)
    return f"✗ Rejected: {approval.action}" + (f" – {reason}" if reason else "")


async def _start_line(db, approval: Approval) -> str:
    """The resumed workflow start's outcome, kept apart from the approval's: a typed refusal names its state and
    reason (``needs_configuration`` / ``workspace_required``) and what to do."""
    from ...models import Session as AgentSession
    from ..workflow_routing.proposal_approval import START_STARTED, workflow_start_outcome

    session = await db.get(AgentSession, approval.session_id, populate_existing=True) if approval.session_id else None
    outcome = workflow_start_outcome(session, approval)
    if outcome is None:
        return ""
    if outcome["state"] == START_STARTED:
        return " – the workflow run started."
    typed = f" ({outcome['state']}: {outcome['reason']})" if outcome["reason"] else ""
    return f" – the workflow did not start{typed}: {outcome['message']}"


def _refusal(short_id: str, exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    if exc.status_code == 404:
        return f"Approval {short_id} not found."
    if detail.get("code") == "strategy_approval_timed_out":
        return f"Approval {short_id} timed out before a decision; the gate's timeout decided it."
    if exc.status_code == 403:
        return f"You are not allowed to decide approval {short_id}."
    return f"Approval {short_id} could not be decided."


__all__ = ["APPROVE_RE", "REJECT_RE", "SENDER_UNRESOLVED_REPLY", "handle_approval_command", "is_approval_command"]
