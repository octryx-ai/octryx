"""Reads for the episode turn capture: the finished turn and the session's current episode text."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Message
from ....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceRevision,
)
from .writer import MAX_EPISODE_CHARS, SOURCE_KEY_PREFIX

MAX_PREVIOUS_SUMMARY_CHARS = MAX_EPISODE_CHARS
MAX_PREVIOUS_SPANS = 200


async def _finished_turn(db: AsyncSession, session_id: str) -> tuple[Message, Message] | None:
    question = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id, Message.role == "user")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if question is None:
        return None
    answer = (
        (
            await db.execute(
                select(Message)
                .where(
                    Message.session_id == session_id,
                    Message.role == "assistant",
                    Message.created_at >= question.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if answer is None or not str(answer.content or "").strip():
        return None
    return question, answer


async def _latest_episode(db: AsyncSession, project_id: str, session_id: str) -> KnowledgeSourceRevision | None:
    return (
        (
            await db.execute(
                select(KnowledgeSourceRevision)
                .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
                .where(
                    KnowledgeEvidenceSource.project_id == project_id,
                    KnowledgeSourceRevision.project_id == project_id,
                    KnowledgeEvidenceSource.source_key == f"{SOURCE_KEY_PREFIX}{session_id}",
                )
                .order_by(KnowledgeSourceRevision.revision_ordinal.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def _summary_text(db: AsyncSession, revision: KnowledgeSourceRevision | None) -> str:
    if revision is None:
        return ""
    spans = (
        await db.execute(
            select(KnowledgeEvidenceSpan.text)
            .where(
                KnowledgeEvidenceSpan.project_id == revision.project_id,
                KnowledgeEvidenceSpan.revision_id == revision.id,
            )
            .order_by(KnowledgeEvidenceSpan.span_ordinal)
            .limit(MAX_PREVIOUS_SPANS)
        )
    ).scalars()
    return "\n\n".join(str(text).strip() for text in spans)[:MAX_PREVIOUS_SUMMARY_CHARS]
