"""Read answer feedback: the Workspace's learning surface and each person's own ratings.

- ``list_feedback`` and ``summarize_feedback`` are pinned to one authorized Workspace; the route
  gates them to the Workspace admin or owner. Filters are closed values (``rating``, ``aspect``) or a
  bounded workflow token, validated like the write path; anything else is ``invalid_request``.
- ``own_feedback_entries`` returns only the caller's own records for a page of messages: the chat
  shows a person their own rating to edit, never someone else's.

Everything is counted and filtered in SQL; at most ``MAX_LISTED`` records come back.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_answer_feedback import KnowledgeAnswerFeedback, KnowledgeAnswerFeedbackAspect
from ....models.project.knowledge_memory import KnowledgeMemoryItem
from ...session.turn_execution_snapshot import safe_token
from ..access.authorization import AuthorizedWorkspace
from .errors import MemoryRefusedError
from .feedback_contract import ASPECTS, RATINGS, VERDICTS
from .presentation import session_link
from .recall import usernames

MAX_LISTED = 200
DEFAULT_LISTED = 50
_MAX_WORKFLOW_KEY_CHARS = 160


@dataclass(frozen=True, slots=True)
class FeedbackFilter:
    rating: str | None = None
    aspect: str | None = None
    workflow_key: str | None = None
    limit: int = DEFAULT_LISTED


def _optional_closed(value: object, allowed: frozenset[str] | tuple[str, ...]) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in allowed:
        raise MemoryRefusedError("invalid_request")
    return value


def parse_feedback_filter(
    *, rating: object = None, aspect: object = None, workflow_key: object = None, limit: object = None
) -> FeedbackFilter:
    workflow = None
    if workflow_key is not None and workflow_key != "":
        workflow = safe_token(workflow_key)
        if workflow is None or workflow != workflow_key or len(workflow) > _MAX_WORKFLOW_KEY_CHARS:
            raise MemoryRefusedError("invalid_request")
    if limit is None:
        limit = DEFAULT_LISTED
    if type(limit) is not int or not 1 <= limit <= MAX_LISTED:
        raise MemoryRefusedError("invalid_request")
    return FeedbackFilter(
        rating=_optional_closed(rating, RATINGS),
        aspect=_optional_closed(aspect, ASPECTS),
        workflow_key=workflow,
        limit=limit,
    )


def _filtered(project_id: str, where: FeedbackFilter):
    row = KnowledgeAnswerFeedback
    conditions = [row.project_id == project_id]
    if where.rating:
        conditions.append(row.rating == where.rating)
    if where.workflow_key:
        conditions.append(row.workflow_key == where.workflow_key)
    if where.aspect:
        aspect = KnowledgeAnswerFeedbackAspect
        conditions.append(row.id.in_(select(aspect.feedback_id).where(aspect.aspect == where.aspect)))
    return conditions


async def _aspects_by_feedback(db: AsyncSession, feedback_ids: Sequence[str]) -> dict[str, dict[str, str]]:
    if not feedback_ids:
        return {}
    aspect = KnowledgeAnswerFeedbackAspect
    rows = await db.execute(
        select(aspect.feedback_id, aspect.aspect, aspect.verdict).where(aspect.feedback_id.in_(list(feedback_ids)))
    )
    found: dict[str, dict[str, str]] = {}
    for feedback_id, name, verdict in rows.all():
        found.setdefault(str(feedback_id), {})[str(name)] = str(verdict)
    # The closed order of the contract, so every reader sees the same sequence.
    return {key: {name: marked[name] for name in ASPECTS if name in marked} for key, marked in found.items()}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def list_feedback(db: AsyncSession, *, authorized: AuthorizedWorkspace, where: FeedbackFilter) -> list[dict]:
    """The Workspace's feedback, newest first, with its links and the memory item's state."""
    row = KnowledgeAnswerFeedback
    rows = list(
        (
            await db.execute(
                select(row)
                .where(*_filtered(authorized.project_id, where))
                .order_by(row.updated_at.desc(), row.id)
                .limit(where.limit)
            )
        ).scalars()
    )
    aspects = await _aspects_by_feedback(db, [item.id for item in rows])
    item_ids = [item.memory_item_id for item in rows if item.memory_item_id]
    states = (
        dict(
            (
                await db.execute(
                    select(KnowledgeMemoryItem.id, KnowledgeMemoryItem.state).where(
                        KnowledgeMemoryItem.id.in_(item_ids)
                    )
                )
            ).all()
        )
        if item_ids
        else {}
    )
    names = await usernames(db, {item.user_id for item in rows if item.user_id})
    return [
        {
            "id": item.id,
            "memory_item_id": item.memory_item_id,
            "memory_state": states.get(item.memory_item_id),
            "rating": item.rating,
            "liked": item.liked,
            "disliked": item.disliked,
            "aspects": aspects.get(item.id, {}),
            "workflow_key": item.workflow_key,
            "workflow_id": item.workflow_id,
            "execution_profile_id": item.execution_profile_id,
            "provider": item.provider,
            "model": item.model,
            "session_id": item.session_id,
            "message_id": item.message_id,
            "session_link": session_link(item.session_id),
            "recorded_by": names.get(item.user_id or ""),
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }
        for item in rows
    ]


async def summarize_feedback(db: AsyncSession, *, authorized: AuthorizedWorkspace, where: FeedbackFilter) -> dict:
    """Good/bad per workflow and liked/disliked per aspect, over the same filters as the list."""
    row = KnowledgeAnswerFeedback
    conditions = _filtered(authorized.project_id, where)
    by_workflow: dict[str | None, dict[str, int]] = {}
    totals = dict.fromkeys(sorted(RATINGS), 0)
    for workflow_key, rating, count in (
        await db.execute(
            select(row.workflow_key, row.rating, func.count()).where(*conditions).group_by(row.workflow_key, row.rating)
        )
    ).all():
        if rating in totals:
            totals[rating] += int(count)
            by_workflow.setdefault(workflow_key, dict.fromkeys(sorted(RATINGS), 0))[rating] += int(count)
    aspect = KnowledgeAnswerFeedbackAspect
    counted = {name: dict.fromkeys(sorted(VERDICTS), 0) for name in ASPECTS}
    for name, verdict, count in (
        await db.execute(
            select(aspect.aspect, aspect.verdict, func.count())
            .where(aspect.feedback_id.in_(select(row.id).where(*conditions)))
            .group_by(aspect.aspect, aspect.verdict)
        )
    ).all():
        if name in counted and verdict in counted[name]:
            counted[name][verdict] = int(count)
    workflows = sorted(by_workflow.items(), key=lambda entry: (entry[0] is None, entry[0] or ""))
    return {
        "workspace_id": authorized.project_id,
        "total": sum(totals.values()),
        **totals,
        "by_workflow": [{"workflow_key": key, **counts} for key, counts in workflows],
        "by_aspect": [{"aspect": name, **counted[name]} for name in ASPECTS],
    }


async def own_feedback_entries(db: AsyncSession, *, user_id: str, message_ids: Sequence[str]) -> list[dict[str, Any]]:
    """The caller's own feedback on these messages, for the chat to show and edit."""
    if not message_ids:
        return []
    row = KnowledgeAnswerFeedback
    rows = list(
        (await db.execute(select(row).where(row.user_id == user_id, row.message_id.in_(list(message_ids))))).scalars()
    )
    aspects = await _aspects_by_feedback(db, [item.id for item in rows])
    return [
        {
            "id": item.id,
            "message_id": item.message_id,
            "rating": item.rating,
            "liked": item.liked,
            "disliked": item.disliked,
            "aspects": aspects.get(item.id, {}),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for item in rows
    ]


__all__ = [
    "DEFAULT_LISTED",
    "MAX_LISTED",
    "FeedbackFilter",
    "list_feedback",
    "own_feedback_entries",
    "parse_feedback_filter",
    "summarize_feedback",
]
