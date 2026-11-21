"""Service-owned session message feedback behavior."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ConflictError
from app.exceptions.base import NotFoundError
from app.exceptions.contract import with_error_contract

from ...models import Message, Session, User
from ...models.session import MessageFeedback
from ...services.knowledge.memory.errors import MemoryRefusedError
from ...services.knowledge.memory.feedback_capture import record_answer_feedback
from ...services.knowledge.memory.feedback_contract import TRANSPORT_RATING, parse_answer_feedback
from ...services.knowledge.memory.feedback_query import own_feedback_entries
from ...time_utils import utc_isoformat


@dataclass(frozen=True, slots=True)
class SessionFeedbackRecord:
    """One person's feedback on one answer, as kept in the Memory lobe (``knowledge_answer_feedback``)."""

    id: str
    message_id: str
    rating: str
    liked: str | None
    disliked: str | None
    aspects: dict[str, str]
    created_at: str
    updated_at: str


# The explicit lobe state of a refused feedback, as the transports render it.
REFUSAL_HTTP_STATUS = {"invalid_request": 422, "denied": 422, "not_found": 404, "needs_configuration": 409}


class SessionFeedbackRefusedError(ConflictError):
    """The feedback was refused for one fixed reason of the Memory lobe (``MemoryRefusedError``)."""

    def __init__(self, error: MemoryRefusedError) -> None:
        super().__init__(error.message)
        self.reason = error.reason
        self.state = error.state

    @property
    def http_status(self) -> int:
        return REFUSAL_HTTP_STATUS.get(self.state, 422)


def refused_feedback(error: MemoryRefusedError) -> Exception:
    """The contract-carrying refusal for a lobe refusal, raised by the service and by the routes' parsing."""
    return _with_feedback_contract(SessionFeedbackRefusedError(error), error_code=f"session_feedback_{error.reason}")


def _with_feedback_contract(exception: Exception, *, error_code: str) -> Exception:
    return with_error_contract(exception, error_code=error_code, retryable=False)


async def submit_session_message_feedback(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str,
    rating: object,
    liked: object = None,
    disliked: object = None,
    aspects: object = None,
    user_id: str,
) -> SessionFeedbackRecord:
    """Record or replace the user's feedback on an assistant answer, in the Workspace's Memory lobe.

    The payload is validated first (``feedback_contract.parse_answer_feedback``: closed values, bounded
    texts, secrets refused). The lobe record and the integer transport row (``message_feedbacks``, read
    by analytics) commit together; the transport row keeps no text. A refusal writes nothing.
    """
    try:
        feedback = parse_answer_feedback(rating=rating, liked=liked, disliked=disliked, aspects=aspects)
    except MemoryRefusedError as error:
        raise refused_feedback(error) from None
    result = await db.execute(select(Session).where(Session.id == session_id, Session.user_id == user_id))
    session = result.scalar_one_or_none()
    if not session:
        raise _with_feedback_contract(
            NotFoundError("Session"),
            error_code="session_feedback_session_not_found",
        )

    result = await db.execute(select(Message).where(Message.id == message_id, Message.session_id == session_id))
    message = result.scalar_one_or_none()
    if not message:
        raise _with_feedback_contract(
            NotFoundError("Message"),
            error_code="session_feedback_message_not_found",
        )
    if message.role != "assistant":
        raise _with_feedback_contract(
            ConflictError("Only assistant messages can be rated"),
            error_code="session_feedback_assistant_only",
        )

    result = await db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == user_id,
        )
    )
    transport = result.scalar_one_or_none()
    user = await db.get(User, user_id)
    try:
        recorded = await record_answer_feedback(db, user=user, session=session, message=message, feedback=feedback)
    except MemoryRefusedError as error:
        # Every refusal happens before anything is written.
        raise refused_feedback(error) from None
    if transport is None:
        transport = MessageFeedback(id=str(uuid.uuid4()), message_id=message_id, user_id=user_id)
        db.add(transport)
    transport.rating = TRANSPORT_RATING[feedback.rating]
    transport.comment = None
    await db.commit()
    entries = await own_feedback_entries(db, user_id=user_id, message_ids=[recorded.feedback.message_id])
    return _feedback_record(entries[0])


async def get_session_message_feedback(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str,
    user_id: str,
) -> SessionFeedbackRecord | None:
    result = await db.execute(select(Session).where(Session.id == session_id, Session.user_id == user_id))
    if not result.scalar_one_or_none():
        raise LookupError("session_not_found")

    entries = await own_feedback_entries(db, user_id=user_id, message_ids=[message_id])
    return _feedback_record(entries[0]) if entries else None


def _feedback_record(entry: dict) -> SessionFeedbackRecord:
    return SessionFeedbackRecord(
        id=entry["id"],
        message_id=entry["message_id"],
        rating=entry["rating"],
        liked=entry["liked"],
        disliked=entry["disliked"],
        aspects=dict(entry["aspects"]),
        created_at=utc_isoformat(entry["created_at"]) or "",
        updated_at=utc_isoformat(entry["updated_at"]) or "",
    )


__all__ = [
    "SessionFeedbackRecord",
    "SessionFeedbackRefusedError",
    "get_session_message_feedback",
    "refused_feedback",
    "submit_session_message_feedback",
]
