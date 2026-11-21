"""Reading the ledger's spans and re-resolving citations (split from ``revisions.py``).

The projection is never trusted for lineage: every retrieved evidence key is resolved here, inside
one Workspace, to its span, revision, source, origin link and scope. Only the source's current
revision is served.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeRevisionScope,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from ....models.project.knowledge_parsing import KnowledgeSpanLocator
from ..access.source_acl import visible_source
from ..sources.source_url import line_link, page_link
from .errors import EvidenceLedgerContractError


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """A citation re-resolved from PostgreSQL, never trusted from the projection."""

    evidence_key: str
    citation: str
    revision_id: str
    span_ordinal: int
    object_bucket: str
    object_key: str
    content_sha256: str
    source_title: str
    source_url: str | None
    # Structured locator: which revision, and where in it.
    source_id: str = ""
    revision_ordinal: int = 0
    char_start: int = 0
    char_end: int = 0
    products: tuple[str, ...] = ()
    version: str | None = None
    # Parsed documents: where in the document the span is; absent for text-native spans.
    kind: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    # Code spans: the 1-based, inclusive line range the link opens at.
    line_start: int | None = None
    line_end: int | None = None
    # The span's own text, the one a hit quotes: the projection may index more than it.
    text: str = ""


async def load_spans(
    db: AsyncSession,
    project_id: str,
    revision_id: str,
    *,
    after_ordinal: int = 0,
    limit: int | None = None,
) -> tuple[KnowledgeEvidenceSpan, ...]:
    """Ordered spans of one revision inside one Workspace.

    ``after_ordinal`` is the projection cursor and ``limit`` the batch bound, so a
    revision with thousands of spans is read in bounded slices rather than whole.
    """
    if type(after_ordinal) is not int or after_ordinal < 0:
        raise EvidenceLedgerContractError()
    statement = (
        select(KnowledgeEvidenceSpan)
        .where(
            KnowledgeEvidenceSpan.project_id == project_id,
            KnowledgeEvidenceSpan.revision_id == revision_id,
            KnowledgeEvidenceSpan.span_ordinal > after_ordinal,
        )
        .order_by(KnowledgeEvidenceSpan.span_ordinal)
    )
    if limit is not None:
        if type(limit) is not int or limit < 1:
            raise EvidenceLedgerContractError()
        statement = statement.limit(limit)
    return tuple((await db.execute(statement)).scalars().all())


def _citation_statement(project_id: str, evidence_keys: tuple[str, ...], principal_keys: tuple[str, ...]):
    return (
        select(
            KnowledgeEvidenceSpan.evidence_key,
            KnowledgeEvidenceSpan.citation,
            KnowledgeEvidenceSpan.revision_id,
            KnowledgeEvidenceSpan.span_ordinal,
            KnowledgeSourceRevision.object_bucket,
            KnowledgeSourceRevision.object_key,
            KnowledgeSourceRevision.content_sha256,
            KnowledgeEvidenceSource.display_title,
            KnowledgeSourceRevisionOrigin.source_url,
            KnowledgeSourceRevision.source_id,
            KnowledgeSourceRevision.revision_ordinal,
            KnowledgeEvidenceSpan.char_start,
            KnowledgeEvidenceSpan.char_end,
            KnowledgeRevisionScope.products,
            KnowledgeRevisionScope.version,
            KnowledgeSourceRevision.media_type,
            KnowledgeSpanLocator.kind,
            KnowledgeSpanLocator.page_start,
            KnowledgeSpanLocator.page_end,
            KnowledgeSpanLocator.section_path,
            KnowledgeSpanLocator.line_start,
            KnowledgeSpanLocator.line_end,
            KnowledgeEvidenceSpan.text,
        )
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeEvidenceSpan.revision_id)
        .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
        .outerjoin(
            KnowledgeSourceRevisionOrigin,
            (KnowledgeSourceRevisionOrigin.revision_id == KnowledgeSourceRevision.id)
            & (KnowledgeSourceRevisionOrigin.project_id == project_id),
        )
        .outerjoin(
            KnowledgeRevisionScope,
            (KnowledgeRevisionScope.revision_id == KnowledgeSourceRevision.id)
            & (KnowledgeRevisionScope.project_id == project_id),
        )
        .outerjoin(
            KnowledgeSpanLocator,
            (KnowledgeSpanLocator.revision_id == KnowledgeEvidenceSpan.revision_id)
            & (KnowledgeSpanLocator.span_ordinal == KnowledgeEvidenceSpan.span_ordinal)
            & (KnowledgeSpanLocator.project_id == project_id),
        )
        .where(
            KnowledgeEvidenceSpan.project_id == project_id,
            KnowledgeSourceRevision.project_id == project_id,
            KnowledgeEvidenceSpan.evidence_key.in_(evidence_keys),
            # Only the source's current revision is served; a superseded or
            # tombstoned revision's spans are history, even while their retirement from
            # the Workspace database is still pending.
            KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
            KnowledgeEvidenceSource.project_id == project_id,
            visible_source(project_id, KnowledgeEvidenceSource.source_key, principal_keys),
        )
    )


def _resolved_citation(row) -> ResolvedCitation:
    return ResolvedCitation(
        evidence_key=row[0],
        citation=row[1],
        revision_id=row[2],
        span_ordinal=row[3],
        object_bucket=row[4],
        object_key=row[5],
        content_sha256=row[6],
        source_title=row[7],
        # A PDF citation opens at its page, a code citation at its lines.
        source_url=line_link(page_link(row[8], row[15], row[17]), row[20], row[21]),
        source_id=row[9],
        revision_ordinal=row[10],
        char_start=row[11],
        char_end=row[12],
        products=tuple(row[13] or ()),
        version=row[14],
        kind=row[16],
        page_start=row[17],
        page_end=row[18],
        section_path=tuple(row[19] or ()),
        line_start=row[20],
        line_end=row[21],
        text=row[22],
    )


async def resolve_citations(
    db: AsyncSession, project_id: str, evidence_keys: tuple[str, ...], *, principal_keys: tuple[str, ...] = ()
) -> dict[str, ResolvedCitation]:
    """Re-resolve evidence keys to their citation and source revision.

    Scoped to one Workspace, so a key that exists in another Workspace simply
    does not resolve and its evidence is dropped from the bundle. A key of a restricted source
    resolves only for a reader whose ``principal_keys`` it admits; none admits none.
    """
    if not evidence_keys:
        return {}
    statement = _citation_statement(project_id, evidence_keys, principal_keys)
    resolved: dict[str, ResolvedCitation] = {}
    for row in (await db.execute(statement)).all():
        resolved[row[0]] = _resolved_citation(row)
    return resolved


async def load_revision_scope(db: AsyncSession, project_id: str, revision_id: str) -> tuple[tuple[str, ...], str]:
    """``(products, version)`` of one revision; ``((), "")`` when it has no scope row."""
    row = (
        await db.execute(
            select(KnowledgeRevisionScope.products, KnowledgeRevisionScope.version).where(
                KnowledgeRevisionScope.revision_id == revision_id,
                KnowledgeRevisionScope.project_id == project_id,
            )
        )
    ).first()
    if row is None:
        return (), ""
    return tuple(row[0] or ()), row[1] or ""


__all__ = ["ResolvedCitation", "load_revision_scope", "load_spans", "resolve_citations"]
