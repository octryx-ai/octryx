"""Rows one revision registration writes, and the request check before any of them.

The source row (created, or retitled), the revision with its spans, the span locators,
origin link and scope that hang off it, and its first outbox obligation. All of them run
inside the caller's one transaction; the caller owns the flush that orders them and the
commit that ends it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    OUTBOX_STATE_PENDING,
    REVISION_STATE_REGISTERED,
    KnowledgeEvidenceSource,
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeRevisionScope,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from ....models.project.knowledge_parsing import SPAN_KIND_CODE, SPAN_KIND_TEXT, KnowledgeSpanLocator
from ....time_utils import ensure_utc, utc_now
from ..access.authorization import AuthorizedWorkspace
from ..ingestion.spans import DerivedSpan, derive_citation, derive_evidence_key
from ..objects import StoredObject
from .errors import EvidenceLedgerContractError
from .lifecycle import create_head, want_revision
from .revision_races import _STAGE_SOURCE, _RevisionInsertConflictError


def _naive_utc(value: datetime | None) -> datetime | None:
    """Stored like every timestamp here: naive UTC."""
    return ensure_utc(value).replace(tzinfo=None) if value is not None else None


async def _ensure_source(
    db: AsyncSession,
    *,
    project_id: str,
    source_id: str | None,
    source_key: str,
    display_title: str,
    created_by: str | None,
) -> str:
    """The source the new revision belongs to: created on first upload, retitled otherwise."""
    if source_id is None:
        source_id = str(uuid.uuid4())
        db.add(
            KnowledgeEvidenceSource(
                id=source_id,
                project_id=project_id,
                source_key=source_key,
                display_title=display_title,
                created_by=created_by,
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            raise _RevisionInsertConflictError(stage=_STAGE_SOURCE, attempted_ordinal=None) from None
    else:
        # A new revision carries the source's current title (a renamed Confluence page), so the
        # Sources list shows what the source is called now. Identical bytes never reach this point.
        await db.execute(
            update(KnowledgeEvidenceSource)
            .where(
                KnowledgeEvidenceSource.id == source_id,
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeEvidenceSource.display_title != display_title,
            )
            .values(display_title=display_title)
        )
    return source_id


def _add_revision_details(
    db: AsyncSession,
    *,
    project_id: str,
    revision_id: str,
    spans: tuple[DerivedSpan, ...],
    source_url: str | None,
    source_changed_at: datetime | None,
    products: tuple[str, ...],
    version: str | None,
) -> None:
    """Span locators, origin link and scope of a revision whose row is already flushed."""
    # After the flush of the revision, like the outbox entry: these rows reference the revision by a
    # foreign key without an ORM relationship, so only that flush makes PostgreSQL see the revision first.
    for span in spans:
        # Markdown and AsciiDoc spans know their section; code spans their lines.
        if span.section_path or span.line_start is not None:
            db.add(
                KnowledgeSpanLocator(
                    revision_id=revision_id,
                    span_ordinal=span.span_ordinal,
                    project_id=project_id,
                    kind=SPAN_KIND_TEXT if span.line_start is None else SPAN_KIND_CODE,
                    section_path=list(span.section_path),
                    line_start=span.line_start,
                    line_end=span.line_end,
                )
            )
    if source_url is not None:
        db.add(KnowledgeSourceRevisionOrigin(revision_id=revision_id, project_id=project_id, source_url=source_url,
                                             source_changed_at=_naive_utc(source_changed_at)))
    if products or version is not None:
        # Set with the revision and never changed by a repeat upload of the same bytes.
        db.add(
            KnowledgeRevisionScope(
                revision_id=revision_id, project_id=project_id, products=list(products), version=version
            )
        )


def _checked_digest(
    authorized: object, stored: object, spans: tuple[DerivedSpan, ...], pending_parse: object
) -> str:
    """The content digest of a well-formed registration request; anything else is a contract error."""
    if type(authorized) is not AuthorizedWorkspace or type(stored) is not StoredObject:
        raise EvidenceLedgerContractError()
    if type(pending_parse) is not bool or (pending_parse and spans):
        raise EvidenceLedgerContractError()
    if not pending_parse and (not spans or not all(type(span) is DerivedSpan for span in spans)):
        raise EvidenceLedgerContractError()
    digest = stored.ref.content_sha256
    if type(digest) is not str:
        raise EvidenceLedgerContractError()
    return digest


def _add_revision_and_spans(
    db: AsyncSession,
    *,
    project_id: str,
    source_id: str,
    revision_id: str,
    revision_ordinal: int,
    digest: str,
    display_title: str,
    media_type: str,
    stored: StoredObject,
    spans: tuple[DerivedSpan, ...],
    parser: tuple[str, str, str],
) -> None:
    parser_name, parser_version, parser_sandbox = parser
    db.add(
        KnowledgeSourceRevision(
            id=revision_id,
            source_id=source_id,
            project_id=project_id,
            revision_ordinal=revision_ordinal,
            content_sha256=digest,
            byte_size=stored.byte_size,
            media_type=media_type,
            object_bucket=stored.ref.bucket,
            object_key=stored.ref.key,
            object_version_id=stored.ref.version_id,
            parser_name=parser_name,
            parser_version=parser_version,
            parser_sandbox=parser_sandbox,
            state=REVISION_STATE_REGISTERED,
            span_count=len(spans),
        )
    )
    for span in spans:
        db.add(
            KnowledgeEvidenceSpan(
                id=str(uuid.uuid4()),
                revision_id=revision_id,
                project_id=project_id,
                span_ordinal=span.span_ordinal,
                evidence_key=derive_evidence_key(revision_id, span.span_ordinal),
                char_start=span.char_start,
                char_end=span.char_end,
                text=span.text,
                citation=derive_citation(display_title, revision_ordinal, span),
            )
        )


async def _owe_first_operation(
    db: AsyncSession, *, project_id: str, source_id: str, revision_id: str, new_source: bool, first_operation: str
) -> None:
    # The newest upload is what the source says; it is served once its projection completes.
    if new_source:
        create_head(db, project_id=project_id, source_id=source_id, revision_id=revision_id)
    else:
        await want_revision(db, project_id=project_id, source_id=source_id, revision_id=revision_id)
    db.add(
        KnowledgeProjectionOutboxEntry(
            id=str(uuid.uuid4()),
            project_id=project_id,
            revision_id=revision_id,
            operation=first_operation,
            state=OUTBOX_STATE_PENDING,
            next_attempt_at=utc_now(),
        )
    )
