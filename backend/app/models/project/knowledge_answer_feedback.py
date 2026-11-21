"""Answer feedback in the Memory lobe: what a person liked and disliked about one assistant answer.

Every rating is one structured record per (user, assistant message); re-submitting replaces it. The
record carries the verdict (``good``/``bad``), the optional "what was good" / "what was not good"
texts, the aspects marked liked or disliked, and the links of the answer: session, message, workflow,
execution profile and the model/provider that answered. Its rendered form is a Workspace-scope memory
item of class ``answer_feedback`` (``knowledge_memory_items``), stated by the person
(``human_stated``), so it is recallable with an explicit class filter and forgettable like any
memory. Feedback is never injected into a prompt.

- ``session_id`` and ``message_id`` are plain references without a foreign key: memory outlives the
  chat that produced it, exactly like ``knowledge_memory_items.session_id``.
- Forgetting the memory item erases ``liked`` and ``disliked`` here too; the verdict and the aspects
  stay as the tombstone's counts.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


class FeedbackRating(StrEnum):
    GOOD = "good"
    BAD = "bad"


class FeedbackAspect(StrEnum):
    CORRECTNESS = "correctness"
    SOURCES = "sources"
    COMPLETENESS = "completeness"
    CLARITY = "clarity"
    TOOL_USE = "tool_use"
    SPEED = "speed"


class AspectVerdict(StrEnum):
    LIKED = "liked"
    DISLIKED = "disliked"


# Each text is bounded so the rendered memory text stays inside the lobe's 2000-character bound.
MAX_FEEDBACK_TEXT_CHARS = 800


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeAnswerFeedback(Base):
    __tablename__ = "knowledge_answer_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_knowledge_answer_feedback_message_user"),
        Index("ix_knowledge_answer_feedback_workspace", "project_id", "rating", "workflow_key"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    memory_item_id = Column(String(36), ForeignKey("knowledge_memory_items.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(64), nullable=False)
    message_id = Column(String(36), nullable=False)
    rating = Column(String(10), nullable=False)
    # Erased (NULL) once the memory item is forgotten.
    liked = Column(Text, nullable=True)
    disliked = Column(Text, nullable=True)
    # Links of the answer, as bounded tokens from its turn trace (NULL when the turn recorded none).
    workflow_key = Column(String(160), nullable=True)
    workflow_id = Column(String(160), nullable=True)
    execution_profile_id = Column(String(160), nullable=True)
    provider = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class KnowledgeAnswerFeedbackAspect(Base):
    """One aspect of one feedback, marked liked or disliked; replaced together with its feedback."""

    __tablename__ = "knowledge_answer_feedback_aspects"
    __table_args__ = (Index("ix_knowledge_answer_feedback_aspects_aspect", "aspect", "verdict"),)

    feedback_id = Column(String(36), ForeignKey("knowledge_answer_feedback.id", ondelete="CASCADE"), primary_key=True)
    aspect = Column(String(30), primary_key=True)
    verdict = Column(String(10), nullable=False)


__all__ = [
    "MAX_FEEDBACK_TEXT_CHARS",
    "AspectVerdict",
    "FeedbackAspect",
    "FeedbackRating",
    "KnowledgeAnswerFeedback",
    "KnowledgeAnswerFeedbackAspect",
]
