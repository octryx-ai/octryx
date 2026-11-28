"""The answer-feedback contract: closed values, bounded texts, and the memory rendering. Anything outside it is refused
with a fixed reason, never coerced."""

from __future__ import annotations

from dataclasses import dataclass

from ....models.project.knowledge_answer_feedback import (
    MAX_FEEDBACK_TEXT_CHARS,
    AspectVerdict,
    FeedbackAspect,
    FeedbackRating,
)
from ..text_safety import has_unsafe_chars
from .errors import MemoryRefusedError
from .text_guard import contains_secret, normalize_memory_text

RATINGS = frozenset(member.value for member in FeedbackRating)
ASPECTS = tuple(member.value for member in FeedbackAspect)
VERDICTS = frozenset(member.value for member in AspectVerdict)
# The transport record (``message_feedbacks.rating``) keeps its integer form for analytics.
TRANSPORT_RATING = {FeedbackRating.GOOD.value: 1, FeedbackRating.BAD.value: -1}


@dataclass(frozen=True, slots=True)
class AnswerFeedbackInput:
    rating: str
    liked: str | None
    disliked: str | None
    # (aspect, verdict) pairs in the closed order of ``ASPECTS``.
    aspects: tuple[tuple[str, str], ...]

    def aspect_names(self, verdict: str) -> list[str]:
        return [aspect for aspect, marked in self.aspects if marked == verdict]


def _closed(value: object, allowed: frozenset[str] | tuple[str, ...]) -> str:
    # ``str`` (or a ``StrEnum`` member) with an exact allowed value; no case folding, no numbers.
    if not isinstance(value, str) or value not in allowed:
        raise MemoryRefusedError("invalid_request")
    return str(value)


def _feedback_text(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise MemoryRefusedError("invalid_text")
    text = raw.strip()
    if not text:
        return None
    if len(text) > MAX_FEEDBACK_TEXT_CHARS or has_unsafe_chars(text, allow_line_breaks=True):
        raise MemoryRefusedError("invalid_text")
    if contains_secret(text):
        raise MemoryRefusedError("secret_detected")
    return text


def _aspects(raw: object) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict) or len(raw) > len(ASPECTS):
        raise MemoryRefusedError("invalid_request")
    marked = {_closed(aspect, ASPECTS): _closed(verdict, VERDICTS) for aspect, verdict in raw.items()}
    return tuple((aspect, marked[aspect]) for aspect in ASPECTS if aspect in marked)


def parse_answer_feedback(
    *, rating: object, liked: object = None, disliked: object = None, aspects: object = None
) -> AnswerFeedbackInput:
    return AnswerFeedbackInput(
        rating=_closed(rating, RATINGS),
        liked=_feedback_text(liked),
        disliked=_feedback_text(disliked),
        aspects=_aspects(aspects),
    )


def render_feedback_text(feedback: AnswerFeedbackInput, *, workflow_key: str | None) -> str:
    workflow = f" (workflow {workflow_key})" if workflow_key else ""
    lines = [f"Answer feedback: the answer was {feedback.rating}{workflow}."]
    if feedback.liked:
        lines.append(f"What was good: {feedback.liked}")
    if feedback.disliked:
        lines.append(f"What was not good: {feedback.disliked}")
    for verdict, label in ((AspectVerdict.LIKED.value, "Liked"), (AspectVerdict.DISLIKED.value, "Disliked")):
        names = feedback.aspect_names(verdict)
        if names:
            lines.append(f"{label} aspects: {', '.join(name.replace('_', ' ') for name in names)}")
    return normalize_memory_text("\n".join(lines))


__all__ = [
    "ASPECTS",
    "RATINGS",
    "TRANSPORT_RATING",
    "VERDICTS",
    "AnswerFeedbackInput",
    "parse_answer_feedback",
    "render_feedback_text",
]
