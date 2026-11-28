"""One governed approval record per workflow proposal that waits for the user."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval
from ...models import Session as AgentSession
from .proposal_decision import (
    DECISION_APPLY,
    DECISION_SKIP,
    DECISIONS_METADATA_KEY,
    RESULT_ALREADY_DECIDED,
    RESULT_INVALID,
    RESULT_NOT_FOUND,
    RESULT_NOT_PENDING,
    RESULT_STARTED,
    pending_workflow_proposal,
)
from .proposal_states import WORKFLOW_PROPOSAL_KEY
from .workflow_selection import ROUTING_RESOLUTION_KEY

logger = logging.getLogger(__name__)

PROPOSAL_APPROVAL_ACTION_PREFIX = "workflow_proposal.confirm:"
_PROPOSAL_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

ANSWER_ALLOW_ONCE = "apply"
ANSWER_DENY = "skip"
PROPOSAL_ANSWERS = frozenset({ANSWER_ALLOW_ONCE, ANSWER_DENY})

_APPROVED = "approved"
_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ProposalApprovalResult:
    outcome: str
    decision: str | None = None
    approval_id: str | None = None


def proposal_approval_action(proposal_id: str) -> str:
    return f"{PROPOSAL_APPROVAL_ACTION_PREFIX}{proposal_id}"


def proposal_id_of_approval_action(action: Any) -> str | None:
    if not isinstance(action, str) or not action.startswith(PROPOSAL_APPROVAL_ACTION_PREFIX):
        return None
    proposal_id = action[len(PROPOSAL_APPROVAL_ACTION_PREFIX) :]
    return proposal_id if _PROPOSAL_ID_PATTERN.match(proposal_id) else None


async def _find(db: AsyncSession, *, session_id: str, proposal_id: str) -> Approval | None:
    action = proposal_approval_action(proposal_id)
    query = select(Approval).where(Approval.session_id == session_id, Approval.action == action)
    return (await db.execute(query.order_by(Approval.created_at.desc()))).scalars().first()


async def request_workflow_proposal_approval(db: AsyncSession, *, session_id: str) -> Approval | None:
    session = await db.get(AgentSession, session_id)
    pending = pending_workflow_proposal(session.metadata_ if session is not None else None)
    proposal_id = str((pending or {}).get("proposal_id") or "")
    if session is None or pending is None or not _PROPOSAL_ID_PATTERN.match(proposal_id):
        return None
    existing = await _find(db, session_id=session_id, proposal_id=proposal_id)
    if existing is not None:
        return existing
    from ..session.turn_approval_state import hold_turn_for_approval
    from .phased_start import approval_text, attach_start_draft
    from .proposal_decision import _pending_message_text

    # A phased workflow's card is its start: the Work item, the run location and the steps (``phased_start``).
    start = await attach_start_draft(db, session=session, message=await _pending_message_text(db, session))
    if start is None:
        return None
    approval = Approval(
        session_id=session_id,
        requested_by=session.user_id,
        action=proposal_approval_action(proposal_id),
        reason=approval_text(start),
    )
    db.add(approval)
    await db.flush()
    # Bind the held message to the record: the binding survives the end of the turn.
    hold_turn_for_approval(session, approval_id=approval.id, requested_by=str(session.user_id))
    await db.flush()
    return approval


async def decide_workflow_proposal_approval(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    proposal_id: str,
    answer: str,
    session_factory=None,
) -> ProposalApprovalResult:
    from ..session.approval_decision import decide_session_approval

    clean_answer = str(answer or "").strip().lower()
    clean_proposal_id = str(proposal_id or "").strip()
    if clean_answer not in PROPOSAL_ANSWERS or not _PROPOSAL_ID_PATTERN.match(clean_proposal_id):
        return ProposalApprovalResult(RESULT_INVALID)
    session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user_id))
    ).scalar_one_or_none()
    if session is None:
        return ProposalApprovalResult(RESULT_NOT_FOUND)
    metadata = dict(session.metadata_ or {})
    recorded = dict(metadata.get(DECISIONS_METADATA_KEY) or {}).get(clean_proposal_id)
    if recorded == DECISION_APPLY and clean_answer == ANSWER_ALLOW_ONCE:
        from .phased_start_run import retry_phased_start

        # A phased start whose run did not start is tried again by the next Allow.
        if await retry_phased_start(db, session=session, owner_id=user_id, proposal_id=clean_proposal_id):
            return ProposalApprovalResult(RESULT_STARTED, DECISION_APPLY)
    if recorded:
        return ProposalApprovalResult(RESULT_ALREADY_DECIDED, recorded)
    pending = pending_workflow_proposal(metadata)
    if pending is None or pending.get("proposal_id") != clean_proposal_id:
        return ProposalApprovalResult(RESULT_NOT_PENDING)
    # A held proposal without a record gets one here: every answer decides a record.
    approval = await request_workflow_proposal_approval(db, session_id=session.id)
    if approval is None:
        return ProposalApprovalResult(RESULT_NOT_PENDING)
    if approval.status != "pending":
        return ProposalApprovalResult(RESULT_ALREADY_DECIDED, approval_id=approval.id)
    decided = await decide_session_approval(
        db,
        approval_id=approval.id,
        decider_id=user_id,
        decision=_REJECTED if clean_answer == ANSWER_DENY else _APPROVED,
        reason=None,
        session_factory=session_factory,
    )
    decision = DECISION_SKIP if clean_answer == ANSWER_DENY else DECISION_APPLY
    return ProposalApprovalResult(RESULT_STARTED, decision, decided.id)


async def resume_workflow_proposal_approval(
    db: AsyncSession, *, session: AgentSession, approval: Approval, decision: str, session_factory
) -> bool:
    proposal_id = proposal_id_of_approval_action(approval.action)
    if proposal_id is None:
        return False
    if decision not in {_APPROVED, _REJECTED}:
        await db.commit()
        return True
    from ..session.turn_approval_state import TurnNotResumable, take_paused_turn

    held = await take_paused_turn(db, session, approval_id=approval.id)
    if isinstance(held, TurnNotResumable):
        logger.warning(
            "workflow_proposal.approval_not_resumable",
            extra={"session_id": session.id, "approval_id": approval.id, "reason": held.reason},
        )
        await db.commit()
        return True
    owner_id = held.owner_user_id or str(session.user_id)
    from .phased_start_run import answer_phased_start

    # A phased workflow is started here (Work item + run), never sent again as a chat turn.
    started = await answer_phased_start(db, session=session, owner_id=owner_id, proposal_id=proposal_id,
                                        approved=decision == _APPROVED, message=held.prompt,
                                        approval_id=approval.id, user_message_id=held.user_message_id)
    if not started:
        # The proposal is no longer the session's pending phased start: nothing starts.
        await db.commit()
    logger.info(
        "workflow_proposal.approval_resumed",
        extra={"session_id": session.id, "approval_id": approval.id, "started": started},
    )
    return True


# The resumed start's outcome as an approval answer reports it (``workflow_start``): ``started`` with the run, a typed
# refusal's own state and reason (``needs_configuration`` / ``workspace_required``), or ``failed`` with the step's text.
START_STARTED = "started"
START_FAILED = "failed"


def workflow_start_outcome(session: AgentSession | None, approval: Approval) -> dict[str, Any] | None:
    proposal_id = proposal_id_of_approval_action(approval.action)
    if session is None or proposal_id is None or approval.status != "approved":
        return None
    resolution = dict(session.metadata_ or {}).get(ROUTING_RESOLUTION_KEY)
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    started = record.get("started") if isinstance(record, dict) and record.get("proposal_id") == proposal_id else None
    if not isinstance(started, dict):
        return None
    if started.get("run_id"):
        return {"state": START_STARTED, "reason": None, "message": None, "run_id": started["run_id"]}
    if "error" not in started:
        return None
    return {"state": started.get("state") or START_FAILED, "reason": started.get("reason"),
            "message": str(started["error"]), "run_id": None}


__all__ = [
    "START_FAILED",
    "START_STARTED",
    "workflow_start_outcome",
    "ANSWER_ALLOW_ONCE",
    "ANSWER_DENY",
    "PROPOSAL_ANSWERS",
    "PROPOSAL_APPROVAL_ACTION_PREFIX",
    "ProposalApprovalResult",
    "decide_workflow_proposal_approval",
    "proposal_approval_action",
    "proposal_id_of_approval_action",
    "request_workflow_proposal_approval",
    "resume_workflow_proposal_approval",
]
