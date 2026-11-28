from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._chat import MessageFeedbackRequest

from ....services.session.feedback import (
    SessionFeedbackRecord,
    get_session_message_feedback,
    submit_session_message_feedback,
)

# One request contract for both transports (``/api/v1`` and ``/chat/api``).
FeedbackCreate = MessageFeedbackRequest


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: str
    liked: str | None
    disliked: str | None
    aspects: dict[str, str]
    created_at: str
    updated_at: str


async def submit_message_feedback(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str,
    body: FeedbackCreate,
    user_id: str,
) -> FeedbackResponse:
    feedback = await submit_session_message_feedback(
        db,
        session_id=session_id,
        message_id=message_id,
        rating=body.rating,
        liked=body.liked,
        disliked=body.disliked,
        aspects=body.aspects,
        user_id=user_id,
    )
    return _build_feedback_response(feedback)


async def get_message_feedback(
    db: AsyncSession,
    *,
    session_id: str,
    message_id: str,
    user_id: str,
) -> FeedbackResponse | None:
    feedback = await get_session_message_feedback(
        db,
        session_id=session_id,
        message_id=message_id,
        user_id=user_id,
    )
    return _build_feedback_response(feedback) if feedback else None


def _build_feedback_response(feedback: SessionFeedbackRecord) -> FeedbackResponse:
    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
        liked=feedback.liked,
        disliked=feedback.disliked,
        aspects=feedback.aspects,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )
