"""Record answer feedback in the Memory lobe: one structured record and one memory item per rating. Flushes only; the
caller commits."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message, Session, TurnTrace, User
from ....models.project.knowledge_answer_feedback import KnowledgeAnswerFeedback, KnowledgeAnswerFeedbackAspect
from ....models.project.knowledge_memory import (
    KnowledgeMemoryItem,
    MemoryAuthorClass,
    MemoryClass,
    MemoryScope,
    MemoryState,
)
from ....time_utils import utc_now
from ...session.turn_execution_snapshot import read_turn_execution_snapshot, safe_token
from ..access.authorization import authorize_workspace
from ..ledger.errors import EvidenceLedgerError
from .errors import MemoryRefusedError
from .feedback_contract import AnswerFeedbackInput, render_feedback_text
from .text_guard import content_hash


@dataclass(frozen=True, slots=True)
class AnswerLinks:
    workflow_key: str | None = None
    workflow_id: str | None = None
    execution_profile_id: str | None = None
    provider: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class FeedbackOutcome:
    feedback: KnowledgeAnswerFeedback
    item: KnowledgeMemoryItem
    # "recorded" (first rating of this answer by this person) or "replaced".
    outcome: str


def _bounded(value: object, limit: int) -> str | None:
    token = safe_token(value)
    return token if token is not None and len(token) <= limit else None


async def resolve_answer_links(db: AsyncSession, *, message: Message) -> AnswerLinks:
    trace = (
        await db.execute(
            select(TurnTrace)
            .where(TurnTrace.session_id == message.session_id, TurnTrace.message_id == message.id)
            .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    profile: dict = {}
    if trace is not None:
        status, snapshot = read_turn_execution_snapshot(trace.context_snapshot_json)
        if status == "ok" and snapshot is not None:
            profile = snapshot["execution_profile"]
    return AnswerLinks(
        workflow_key=_bounded(profile.get("workflow_key"), 160),
        workflow_id=_bounded(profile.get("workflow_id"), 160),
        execution_profile_id=_bounded(profile.get("profile_id"), 160),
        provider=_bounded(trace.provider if trace is not None else None, 100),
        model=_bounded((trace.model if trace is not None else None) or message.model, 100),
    )


async def _replace_aspects(db: AsyncSession, row: KnowledgeAnswerFeedback, feedback: AnswerFeedbackInput) -> None:
    existing = {
        aspect.aspect: aspect
        for aspect in (
            await db.execute(
                select(KnowledgeAnswerFeedbackAspect).where(KnowledgeAnswerFeedbackAspect.feedback_id == row.id)
            )
        ).scalars()
    }
    marked = dict(feedback.aspects)
    for name, aspect in existing.items():
        if name not in marked:
            await db.delete(aspect)
    for name, verdict in marked.items():
        if name in existing:
            existing[name].verdict = verdict
        else:
            db.add(KnowledgeAnswerFeedbackAspect(feedback_id=row.id, aspect=name, verdict=verdict))


def _erase(item: KnowledgeMemoryItem, user_id: str) -> None:
    item.text = None
    item.content_hash = None
    item.state = MemoryState.FORGOTTEN.value
    item.state_changed_by = user_id
    item.state_changed_at = utc_now()


async def _write_item(
    db: AsyncSession, *, row: KnowledgeAnswerFeedback, project_id: str, user_id: str, text: str
) -> KnowledgeMemoryItem:
    now = utc_now()
    item = await db.get(KnowledgeMemoryItem, row.memory_item_id) if row.memory_item_id else None
    if item is not None and item.state != MemoryState.FORGOTTEN.value and item.project_id == project_id:
        item.text = text
        item.content_hash = content_hash(text)
        item.state = MemoryState.CONFIRMED.value
        item.state_changed_by = user_id
        item.state_changed_at = now
        return item
    if item is not None and item.text is not None:
        # The chat moved to another Workspace: the old Workspace keeps no copy of the replaced wording.
        _erase(item, user_id)
    item = KnowledgeMemoryItem(
        project_id=project_id,
        scope=MemoryScope.WORKSPACE.value,
        owner_user_id=None,
        item_class=MemoryClass.ANSWER_FEEDBACK.value,
        author_class=MemoryAuthorClass.HUMAN_STATED.value,
        state=MemoryState.CONFIRMED.value,
        text=text,
        content_hash=content_hash(text),
        session_id=row.session_id,
        turn_ref=row.message_id,
        author_user_id=user_id,
        created_at=now,
    )
    db.add(item)
    await db.flush()
    row.memory_item_id = item.id
    return item


async def record_answer_feedback(
    db: AsyncSession, *, user: User, session: Session, message: Message, feedback: AnswerFeedbackInput
) -> FeedbackOutcome:
    if not session.project_id:
        raise MemoryRefusedError("workspace_required")
    try:
        authorized = await authorize_workspace(db, current_user=user, workspace_id=session.project_id)
    except EvidenceLedgerError:
        raise MemoryRefusedError("workspace_not_accessible") from None
    user_id = str(user.id)
    links = await resolve_answer_links(db, message=message)
    text = render_feedback_text(feedback, workflow_key=links.workflow_key)
    now = utc_now()

    row = (
        await db.execute(
            select(KnowledgeAnswerFeedback).where(
                KnowledgeAnswerFeedback.message_id == message.id, KnowledgeAnswerFeedback.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    outcome = "replaced"
    if row is None:
        outcome = "recorded"
        row = KnowledgeAnswerFeedback(user_id=user_id, message_id=message.id, created_at=now)
        db.add(row)
    row.project_id = authorized.project_id
    row.session_id = session.id
    row.rating = feedback.rating
    row.liked = feedback.liked
    row.disliked = feedback.disliked
    row.workflow_key = links.workflow_key
    row.workflow_id = links.workflow_id
    row.execution_profile_id = links.execution_profile_id
    row.provider = links.provider
    row.model = links.model
    row.updated_at = now
    await db.flush()
    await _replace_aspects(db, row, feedback)
    item = await _write_item(db, row=row, project_id=authorized.project_id, user_id=user_id, text=text)
    await db.flush()
    return FeedbackOutcome(feedback=row, item=item, outcome=outcome)


async def erase_forgotten_feedback_texts(db: AsyncSession, memory_item_ids: Iterable[str]) -> None:
    ids = sorted(set(memory_item_ids))
    if not ids:
        return
    await db.execute(
        update(KnowledgeAnswerFeedback)
        .where(KnowledgeAnswerFeedback.memory_item_id.in_(ids))
        .values(liked=None, disliked=None)
    )


__all__ = [
    "AnswerLinks",
    "FeedbackOutcome",
    "erase_forgotten_feedback_texts",
    "record_answer_feedback",
    "resolve_answer_links",
]
