"""The pending workflow proposal of a session, its recorded answers and the chat client's view of it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session
from .proposal_states import STATUS_NEEDS_CONFIRMATION, WORKFLOW_PROPOSAL_KEY
from .workflow_selection import ROUTING_RESOLUTION_KEY

DECISION_APPLY = "apply"
DECISION_SKIP = "skip"
DECISIONS_METADATA_KEY = "workflow_proposal_decisions"
MAX_RECORDED_DECISIONS = 20

RESULT_STARTED = "started"
RESULT_ALREADY_DECIDED = "already_decided"
RESULT_NOT_PENDING = "not_pending"
RESULT_NOT_FOUND = "not_found"
RESULT_INVALID = "invalid_decision"


def pending_workflow_proposal(metadata: Any) -> dict[str, Any] | None:
    resolution = metadata.get(ROUTING_RESOLUTION_KEY) if isinstance(metadata, dict) else None
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    if isinstance(record, dict) and record.get("status") == STATUS_NEEDS_CONFIRMATION and record.get("proposal_id"):
        return record
    return None


def workflow_proposal_view(metadata: Any) -> dict[str, Any] | None:
    resolution = metadata.get(ROUTING_RESOLUTION_KEY) if isinstance(metadata, dict) else None
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    if not isinstance(record, dict):
        return None
    decisions = metadata.get(DECISIONS_METADATA_KEY) if isinstance(metadata.get(DECISIONS_METADATA_KEY), dict) else {}
    proposal_id = record.get("proposal_id")
    return {
        "proposalId": proposal_id,
        "status": record.get("status"),
        "reasonCode": record.get("reason_code"),
        "workflowKey": record.get("workflow_key"),
        "workflowTitle": record.get("workflow_title"),
        "confidence": record.get("confidence"),
        "reason": record.get("reason"),
        "changeCapable": record.get("change_capable"),
        "decision": decisions.get(proposal_id) if proposal_id else None,
        # A phased workflow's start card and, once allowed, what started (``phased_start``).
        "phased": bool(record.get("phased")),
        "start": record.get("start"),
        "started": record.get("started"),
    }


async def _pending_message_text(db: AsyncSession, session: Session) -> str:
    message_id = str((session.metadata_ or {}).get("current_turn_user_message_id") or "").strip()
    message = await db.get(Message, message_id) if message_id else None
    if message is None or message.session_id != session.id or message.role != "user":
        return ""
    return str(message.content or "")


__all__ = [
    "DECISION_APPLY",
    "DECISION_SKIP",
    "RESULT_ALREADY_DECIDED",
    "RESULT_INVALID",
    "RESULT_NOT_FOUND",
    "RESULT_NOT_PENDING",
    "RESULT_STARTED",
    "pending_workflow_proposal",
    "workflow_proposal_view",
]
