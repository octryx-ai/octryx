"""Which revisions a layer reads, and their spans.

Only a source's **current** revision is read (``knowledge_source_heads.current_revision_id`` in
state ``projected``), the same rule every Knowledge read follows; the rest of the graph of a
superseded or removed revision is retired by the build.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceHead,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_parsing import KnowledgeSpanLocator
from .facts import SpanInput


@dataclass(frozen=True, slots=True)
class Candidate:
    revision_id: str
    source_id: str
    source_key: str
    title: str
    media_type: str
    object_bucket: str
    object_key: str
    object_version_id: str | None
    content_sha256: str
    created_at: object = None


async def current_revisions(
    db: AsyncSession,
    project_id: str,
    *,
    media_types: tuple[str, ...] = (),
    source_key_prefixes: tuple[str, ...] = (),
    revision_ids: tuple[str, ...] = (),
) -> list[Candidate]:
    """Current revisions that match **any** of the given selectors, in source-key order."""
    selectors = []
    if media_types:
        selectors.append(KnowledgeSourceRevision.media_type.in_(media_types))
    key = KnowledgeEvidenceSource.source_key
    selectors.extend(key.startswith(prefix, autoescape=True) for prefix in source_key_prefixes)
    if revision_ids:
        selectors.append(KnowledgeSourceRevision.id.in_(revision_ids))
    if not selectors:
        return []
    rows = await db.execute(
        select(
            KnowledgeSourceRevision.id,
            KnowledgeSourceRevision.source_id,
            KnowledgeEvidenceSource.source_key,
            KnowledgeEvidenceSource.display_title,
            KnowledgeSourceRevision.media_type,
            KnowledgeSourceRevision.object_bucket,
            KnowledgeSourceRevision.object_key,
            KnowledgeSourceRevision.object_version_id,
            KnowledgeSourceRevision.content_sha256,
            KnowledgeSourceRevision.created_at,
        )
        .join(KnowledgeSourceHead, KnowledgeSourceHead.current_revision_id == KnowledgeSourceRevision.id)
        .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
        .where(
            and_(
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
                or_(*selectors),
            )
        )
        .order_by(KnowledgeEvidenceSource.source_key)
    )
    return [Candidate(*(str(value) if index < 7 else value for index, value in enumerate(row))) for row in rows.all()]


async def load_span_inputs(db: AsyncSession, project_id: str, revision_id: str) -> list[SpanInput]:
    rows = await db.execute(
        select(
            KnowledgeEvidenceSpan.span_ordinal,
            KnowledgeEvidenceSpan.text,
            KnowledgeSpanLocator.kind,
            KnowledgeSpanLocator.page_start,
            KnowledgeSpanLocator.page_end,
            KnowledgeSpanLocator.section_path,
            KnowledgeSpanLocator.line_start,
            KnowledgeSpanLocator.line_end,
            KnowledgeEvidenceSpan.char_start,
        )
        .outerjoin(
            KnowledgeSpanLocator,
            (KnowledgeSpanLocator.revision_id == KnowledgeEvidenceSpan.revision_id)
            & (KnowledgeSpanLocator.span_ordinal == KnowledgeEvidenceSpan.span_ordinal),
        )
        .where(KnowledgeEvidenceSpan.project_id == project_id, KnowledgeEvidenceSpan.revision_id == revision_id)
        .order_by(KnowledgeEvidenceSpan.span_ordinal)
    )
    return [
        SpanInput(
            int(row[0]), row[1], row[2], row[3], row[4], tuple(str(item) for item in (row[5] or ())), row[6], row[7],
            row[8],
        )
        for row in rows.all()
    ]


__all__ = ["Candidate", "current_revisions", "load_span_inputs"]
