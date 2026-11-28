"""The text the projection indexes and embeds for each span of a revision. The cited text is always read back from the
ledger."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_parsing import SPAN_KIND_CODE, KnowledgeSpanLocator
from ..code.retrieval_text import code_embedding_text, code_retrieval_text

PURPOSE_INDEX = "index"
PURPOSE_EMBED = "embed"


async def _code_sections(
    db: AsyncSession, project_id: str, revision_id: str, ordinals: Sequence[int]
) -> dict[int, tuple[str, ...]]:
    rows = await db.execute(
        select(KnowledgeSpanLocator.span_ordinal, KnowledgeSpanLocator.section_path).where(
            KnowledgeSpanLocator.project_id == project_id,
            KnowledgeSpanLocator.revision_id == revision_id,
            KnowledgeSpanLocator.kind == SPAN_KIND_CODE,
            KnowledgeSpanLocator.span_ordinal.in_(list(ordinals)),
        )
    )
    return {int(ordinal): tuple(str(name) for name in (path or ())) for ordinal, path in rows.all()}


async def _source_title(db: AsyncSession, project_id: str, revision_id: str) -> str:
    title = (
        await db.execute(
            select(KnowledgeEvidenceSource.display_title)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.source_id == KnowledgeEvidenceSource.id)
            .where(KnowledgeSourceRevision.id == revision_id, KnowledgeSourceRevision.project_id == project_id)
        )
    ).scalar_one_or_none()
    return str(title or "")


async def projected_span_texts(
    db: AsyncSession,
    project_id: str,
    revision_id: str,
    spans: Sequence[KnowledgeEvidenceSpan],
    *,
    purpose: str,
) -> dict[int, str]:
    if purpose not in (PURPOSE_INDEX, PURPOSE_EMBED):
        raise ValueError("unknown projection purpose")
    texts = {int(span.span_ordinal): span.text for span in spans}
    sections = await _code_sections(db, project_id, revision_id, list(texts))
    if not sections:
        return texts
    path = await _source_title(db, project_id, revision_id)
    render = code_retrieval_text if purpose == PURPOSE_INDEX else code_embedding_text
    for ordinal, section_path in sections.items():
        texts[ordinal] = render(texts[ordinal], path=path, section_path=section_path)
    return texts


__all__ = ["PURPOSE_EMBED", "PURPOSE_INDEX", "projected_span_texts"]
