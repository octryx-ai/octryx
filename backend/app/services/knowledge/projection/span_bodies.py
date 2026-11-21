"""The text the projection indexes and embeds for each span of a revision.

Most spans are projected as their own text. A **code** span (locator kind ``code``, written by
``ingestion/code_ingest``) is projected as its retrieval text instead
(``code/retrieval_text``): the file path and symbol path of its locator, the words of its
identifiers, then its lines. The projected body is only what the span is found by; the text a
retrieval hit returns and cites is read back from the ledger (``retrieval/evidence.py``).

Read per batch, from the ledger only: the revision's source title (a repository file's path) and
the batch's locators. A span without a locator row is projected as its own text.
"""

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
    """``span_ordinal -> text`` to index (``PURPOSE_INDEX``) or embed (``PURPOSE_EMBED``)."""
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
