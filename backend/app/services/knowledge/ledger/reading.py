"""Read a cited span with its neighbours, from the ledger (the ``read`` operation). The evidence key resolves inside the
authorized Workspace only."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from ....models.project.knowledge_parsing import KnowledgeSpanLocator
from ..access.authorization import AuthorizedWorkspace
from ..access.source_acl import visible_source
from ..retrieval.contracts import is_valid_evidence_id
from ..sources.source_url import line_link
from .errors import EvidenceRecordNotFoundError, InvalidEvidenceRequestError

MAX_READ_WINDOW = 3


@dataclass(frozen=True, slots=True)
class SpanWindow:
    evidence_key: str
    text: str
    citation: str
    source_title: str
    source_url: str | None
    revision_ordinal: int
    current: bool
    first_span: int
    last_span: int
    # Each span of the window with its own evidence key, in order: a fact is cited by the passage that states it.
    passages: tuple[tuple[str, str], ...] = ()


async def _center(db: AsyncSession, project_id: str, evidence_key: str, principal_keys: tuple[str, ...]):
    center = (
        await db.execute(
            select(
                KnowledgeEvidenceSpan.revision_id,
                KnowledgeEvidenceSpan.span_ordinal,
                KnowledgeEvidenceSpan.citation,
                KnowledgeSourceRevision.revision_ordinal,
                KnowledgeSourceRevision.state,
                KnowledgeEvidenceSource.display_title,
                KnowledgeSourceRevisionOrigin.source_url,
            )
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeEvidenceSpan.revision_id)
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .outerjoin(
                KnowledgeSourceRevisionOrigin,
                (KnowledgeSourceRevisionOrigin.revision_id == KnowledgeSourceRevision.id)
                & (KnowledgeSourceRevisionOrigin.project_id == project_id),
            )
            .where(
                KnowledgeEvidenceSpan.project_id == project_id,
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSpan.evidence_key == evidence_key,
                KnowledgeEvidenceSource.project_id == project_id,
                # A restricted source reads only for a reader its ACL admits, history included.
                visible_source(project_id, KnowledgeEvidenceSource.source_key, principal_keys),
            )
        )
    ).first()
    if center is None:
        # Unknown here, belonging to another Workspace, and restricted are the same answer.
        raise EvidenceRecordNotFoundError()
    return center


async def _neighbours(db: AsyncSession, project_id: str, revision_id: str, ordinal: int, window: int):
    return (
        await db.execute(
            select(
                KnowledgeEvidenceSpan.span_ordinal,
                KnowledgeEvidenceSpan.text,
                KnowledgeSpanLocator.line_start,
                KnowledgeSpanLocator.line_end,
                KnowledgeEvidenceSpan.evidence_key,
            )
            .outerjoin(
                KnowledgeSpanLocator,
                (KnowledgeSpanLocator.revision_id == KnowledgeEvidenceSpan.revision_id)
                & (KnowledgeSpanLocator.span_ordinal == KnowledgeEvidenceSpan.span_ordinal)
                & (KnowledgeSpanLocator.project_id == project_id),
            )
            .where(
                KnowledgeEvidenceSpan.project_id == project_id,
                KnowledgeEvidenceSpan.revision_id == revision_id,
                KnowledgeEvidenceSpan.span_ordinal >= ordinal - window,
                KnowledgeEvidenceSpan.span_ordinal <= ordinal + window,
            )
            .order_by(KnowledgeEvidenceSpan.span_ordinal)
        )
    ).all()


async def read_span_window(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, evidence_key: object, window: object = 1
) -> SpanWindow:
    if not is_valid_evidence_id(evidence_key) or type(window) is not int or not 0 <= window <= MAX_READ_WINDOW:
        raise InvalidEvidenceRequestError()
    project_id = authorized.project_id
    center = await _center(db, project_id, evidence_key, authorized.principal_keys)
    revision_id, ordinal, citation, revision_ordinal, state, title, source_url = center
    neighbours = await _neighbours(db, project_id, revision_id, ordinal, window)
    # A code window links the lines it spans: from the first span's start to the last's end.
    starts = [row[2] for row in neighbours]
    ends = [row[3] for row in neighbours]
    if all(isinstance(value, int) for value in starts + ends):
        source_url = line_link(source_url, min(starts), max(ends))
    return SpanWindow(
        evidence_key=evidence_key,
        text="\n\n".join(row[1] for row in neighbours),
        citation=citation,
        source_title=title,
        source_url=source_url,
        revision_ordinal=revision_ordinal,
        current=state == REVISION_STATE_PROJECTED,
        first_span=neighbours[0][0],
        last_span=neighbours[-1][0],
        passages=tuple((row[4], row[1]) for row in neighbours),
    )


__all__ = ["MAX_READ_WINDOW", "SpanWindow", "read_span_window"]
