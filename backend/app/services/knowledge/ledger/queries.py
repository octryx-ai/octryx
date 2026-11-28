"""Bounded read projections of the Evidence ledger for the API surface. Every statement filters on ``project_id``; a
limit out of range is refused, never clamped."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeProjectionOutboxEntry,
    KnowledgeRevisionScope,
    KnowledgeSourceRevision,
)
from ..access.authorization import AuthorizedWorkspace
from ..access.source_acl import visible_source
from .errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError, InvalidEvidenceRequestError

DEFAULT_SOURCE_LIMIT = 50
MAX_SOURCE_LIMIT = 200
MAX_REVISION_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SourceSummary:
    source_id: str
    source_key: str
    display_title: str
    revision_count: int
    latest_revision_ordinal: int | None


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    revision_id: str
    revision_ordinal: int
    content_sha256: str
    media_type: str
    byte_size: int
    span_count: int
    state: str


@dataclass(frozen=True, slots=True)
class SourceDetail:
    source: SourceSummary
    revisions: tuple[RevisionSummary, ...]


@dataclass(frozen=True, slots=True)
class ProjectionBacklog:
    by_state: dict[str, int]

    def count(self, state: str) -> int:
        return int(self.by_state.get(state, 0))


def _validated_limit(limit: object, default: int, maximum: int) -> int:
    # The limit comes from the query string: out of range is a 400, never a 502 contract violation.
    if limit is None:
        return default
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise InvalidEvidenceRequestError()
    return limit


async def list_sources(
    db: AsyncSession, authorized: AuthorizedWorkspace, *, limit: object = None
) -> tuple[SourceSummary, ...]:
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    bounded = _validated_limit(limit, DEFAULT_SOURCE_LIMIT, MAX_SOURCE_LIMIT)
    statement = (
        select(
            KnowledgeEvidenceSource.id,
            KnowledgeEvidenceSource.source_key,
            KnowledgeEvidenceSource.display_title,
            func.count(KnowledgeSourceRevision.id),
            func.max(KnowledgeSourceRevision.revision_ordinal),
        )
        .outerjoin(
            KnowledgeSourceRevision,
            (KnowledgeSourceRevision.source_id == KnowledgeEvidenceSource.id)
            & (KnowledgeSourceRevision.project_id == authorized.project_id),
        )
        .where(
            KnowledgeEvidenceSource.project_id == authorized.project_id,
            # A restricted source's title is listed only for a reader its ACL admits.
            visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
        )
        .group_by(
            KnowledgeEvidenceSource.id,
            KnowledgeEvidenceSource.source_key,
            KnowledgeEvidenceSource.display_title,
            KnowledgeEvidenceSource.created_at,
        )
        .order_by(KnowledgeEvidenceSource.created_at.desc())
        .limit(bounded)
    )
    return tuple(
        SourceSummary(
            source_id=row[0],
            source_key=row[1],
            display_title=row[2],
            revision_count=int(row[3] or 0),
            latest_revision_ordinal=int(row[4]) if row[4] is not None else None,
        )
        for row in (await db.execute(statement)).all()
    )


async def _source_header(db: AsyncSession, authorized: AuthorizedWorkspace, source_id: str):
    header = (
        await db.execute(
            select(
                KnowledgeEvidenceSource.id,
                KnowledgeEvidenceSource.source_key,
                KnowledgeEvidenceSource.display_title,
            ).where(
                KnowledgeEvidenceSource.project_id == authorized.project_id,
                KnowledgeEvidenceSource.id == source_id,
                visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
            )
        )
    ).first()
    if header is None:
        # Foreign and missing are the same outcome: the Workspace predicate above
        # is what makes a foreign source unreachable rather than forbidden.
        raise EvidenceRecordNotFoundError()
    return header


async def _revision_summaries(
    db: AsyncSession, authorized: AuthorizedWorkspace, source_id: str
) -> tuple[RevisionSummary, ...]:
    statement = (
        select(
            KnowledgeSourceRevision.id,
            KnowledgeSourceRevision.revision_ordinal,
            KnowledgeSourceRevision.content_sha256,
            KnowledgeSourceRevision.media_type,
            KnowledgeSourceRevision.byte_size,
            KnowledgeSourceRevision.span_count,
            KnowledgeSourceRevision.state,
        )
        .where(
            KnowledgeSourceRevision.project_id == authorized.project_id,
            KnowledgeSourceRevision.source_id == source_id,
        )
        .order_by(KnowledgeSourceRevision.revision_ordinal.desc())
        .limit(MAX_REVISION_LIMIT)
    )
    return tuple(
        RevisionSummary(
            revision_id=row[0],
            revision_ordinal=int(row[1]),
            content_sha256=row[2],
            media_type=row[3],
            byte_size=int(row[4]),
            span_count=int(row[5]),
            state=row[6],
        )
        for row in (await db.execute(statement)).all()
    )


async def get_source_detail(db: AsyncSession, authorized: AuthorizedWorkspace, source_id: object) -> SourceDetail:
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    if type(source_id) is not str or not source_id or len(source_id) > 36:
        raise EvidenceRecordNotFoundError()
    header = await _source_header(db, authorized, source_id)
    revisions = await _revision_summaries(db, authorized, source_id)
    # Counted, not inferred from the bounded list: a source with more than
    # ``MAX_REVISION_LIMIT`` revisions would otherwise report the limit as its
    # revision count and quietly understate its own history.
    total = (
        await db.execute(
            select(func.count(KnowledgeSourceRevision.id)).where(
                KnowledgeSourceRevision.project_id == authorized.project_id,
                KnowledgeSourceRevision.source_id == source_id,
            )
        )
    ).scalar_one()
    return SourceDetail(
        source=SourceSummary(
            source_id=header[0],
            source_key=header[1],
            display_title=header[2],
            revision_count=int(total or 0),
            latest_revision_ordinal=revisions[0].revision_ordinal if revisions else None,
        ),
        revisions=revisions,
    )


async def projection_backlog(db: AsyncSession, authorized: AuthorizedWorkspace) -> ProjectionBacklog:
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    statement = (
        select(KnowledgeProjectionOutboxEntry.state, func.count(KnowledgeProjectionOutboxEntry.id))
        .where(KnowledgeProjectionOutboxEntry.project_id == authorized.project_id)
        .group_by(KnowledgeProjectionOutboxEntry.state)
    )
    return ProjectionBacklog(by_state={row[0]: int(row[1]) for row in (await db.execute(statement)).all()})


async def workspace_products(db: AsyncSession, authorized: AuthorizedWorkspace) -> dict[str, list[str]]:
    rows = await db.execute(
        select(KnowledgeRevisionScope.products, KnowledgeRevisionScope.version)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeRevisionScope.revision_id)
        .where(
            KnowledgeRevisionScope.project_id == authorized.project_id,
            KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
        )
    )
    found: dict[str, set[str]] = {}
    for products, version in rows.all():
        for product in products or ():
            found.setdefault(product, set()).add(version or "")
    return {product: sorted(versions) for product, versions in sorted(found.items())}

