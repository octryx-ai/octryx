"""PostgreSQL authority for Workspace sources, immutable revisions, and spans. Only the three known insert races are
retried; every other integrity failure is raised."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.recovery_vocabulary import RECOVERY_OPERATION_REQUEUE_ON_REUPLOAD

from ....models.project.knowledge_evidence import OUTBOX_OPERATION_PARSE_REVISION, OUTBOX_OPERATION_PROJECT_REVISION
from ..access.authorization import AuthorizedWorkspace
from ..ingestion.spans import DerivedSpan, new_revision_id
from ..objects import StoredObject
from ..objects.publication_lock import lock_object_publication
from ..projection.recovery import recover_projection
from .errors import EvidenceLedgerContractError, EvidenceRecordNotFoundError, EvidenceStoreUnavailableError
from .lifecycle import want_revision
from .revision_races import (
    _STAGE_REVISION,
    MAX_ORDINAL_RETRIES,
    RegisteredRevision,
    _existing_revision,
    _is_retryable_race,
    _next_ordinal,
    _RevisionInsertConflictError,
    _source_id,
)
from .revision_rows import (
    _add_revision_and_spans,
    _add_revision_details,
    _checked_digest,
    _ensure_source,
    _owe_first_operation,
)

logger = logging.getLogger(__name__)


async def _recover_on_repeat_upload(
    db: AsyncSession, authorized: AuthorizedWorkspace, revision_id: str, actor_user_id: str | None
) -> None:
    # The recovery rule lives in ``projection_recovery``; a healthy obligation is refused there without a write.
    try:
        await recover_projection(
            db,
            authorized=authorized,
            revision_id=revision_id,
            operation=RECOVERY_OPERATION_REQUEUE_ON_REUPLOAD,
            actor_user_id=actor_user_id,
        )
    except EvidenceRecordNotFoundError:
        # A committed revision always carries its obligation, so this is a ledger
        # inconsistency worth reporting — but not one the caller caused, and the
        # idempotent upload outcome does not depend on it.
        logger.error("Knowledge revision has no projection obligation to recover: workspace=%s", authorized.project_id)


async def register_revision(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    source_key: str,
    display_title: str,
    media_type: str,
    stored: StoredObject,
    spans: tuple[DerivedSpan, ...],
    parser_name: str,
    parser_version: str,
    parser_sandbox: str,
    created_by: str | None,
    source_url: str | None = None,
    source_changed_at: datetime | None = None,
    products: tuple[str, ...] = (),
    version: str | None = None,
    pending_parse: bool = False,
) -> RegisteredRevision:
    digest = _checked_digest(authorized, stored, spans, pending_parse)
    insert_fields = dict(
        source_key=source_key,
        display_title=display_title,
        media_type=media_type,
        stored=stored,
        spans=spans,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_sandbox=parser_sandbox,
        created_by=created_by,
        source_url=source_url,
        source_changed_at=source_changed_at,
        products=products,
        version=version,
        first_operation=OUTBOX_OPERATION_PARSE_REVISION if pending_parse else OUTBOX_OPERATION_PROJECT_REVISION,
    )
    return await _register_with_retries(db, authorized, stored, digest, created_by, insert_fields)


async def _adopt_existing(
    db: AsyncSession, authorized: AuthorizedWorkspace, source_id: str | None, digest: str, created_by: str | None
) -> RegisteredRevision | None:
    if source_id is None:
        return None
    existing = await _existing_revision(db, authorized.project_id, source_id, digest)
    if existing is None:
        return None
    # Same bytes remain one revision, and uploading them again makes them what
    # the source says now (an earlier version, or a removed source, comes back).
    # Re-upload also stays the implicit recovery signal for a dead-lettered
    # projection, routed through the one governed, audited transition.
    await want_revision(db, project_id=authorized.project_id, source_id=source_id, revision_id=existing.revision_id)
    await db.commit()
    await _recover_on_repeat_upload(db, authorized, existing.revision_id, created_by)
    return existing


async def _register_with_retries(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    stored: StoredObject,
    digest: str,
    created_by: str | None,
    insert_fields: dict[str, object],
) -> RegisteredRevision:
    project_id = authorized.project_id
    source_key = insert_fields["source_key"]
    for _ in range(MAX_ORDINAL_RETRIES + 1):
        # Re-taken every iteration, because the rollback below ends the transaction that
        # holds it: the publication boundary the ingestion took before it wrote the object
        # must still be held when the reference to that object is committed.
        await lock_object_publication(db, project_id=project_id, object_key=stored.ref.key)
        source_id = await _source_id(db, project_id, source_key)
        existing = await _adopt_existing(db, authorized, source_id, digest, created_by)
        if existing is not None:
            return existing
        try:
            return await _insert_revision(db, project_id=project_id, source_id=source_id, **insert_fields)
        except _RevisionInsertConflictError as conflict:
            # The exception itself is dropped: it carries statement and constraint
            # text that must not reach a caller or a log line. What may be retried
            # is decided by re-reading the ledger instead.
            await db.rollback()
            if not await _is_retryable_race(db, project_id, source_key, digest, conflict):
                logger.error(
                    "Knowledge evidence revision insert failed on an unattributable constraint: stage=%s workspace=%s",
                    conflict.stage,
                    project_id,
                )
                # Not one of the three races: retrying cannot help, and reporting it
                # as contention would tell an operator to try again about a defect.
                raise EvidenceLedgerContractError() from None
    logger.warning(
        "Knowledge evidence revision insert lost %d ordinal races: workspace=%s",
        MAX_ORDINAL_RETRIES + 1,
        project_id,
    )
    # Contention that did not settle inside the bound is retryable, not a fault of
    # the request and not a silent partial success.
    raise EvidenceStoreUnavailableError()


async def _insert_revision(
    db: AsyncSession,
    *,
    project_id: str,
    source_id: str | None,
    source_key: str,
    display_title: str,
    media_type: str,
    stored: StoredObject,
    spans: tuple[DerivedSpan, ...],
    parser_name: str,
    parser_version: str,
    parser_sandbox: str,
    created_by: str | None,
    source_url: str | None,
    products: tuple[str, ...] = (),
    source_changed_at: datetime | None = None,
    version: str | None = None,
    first_operation: str = OUTBOX_OPERATION_PROJECT_REVISION,
) -> RegisteredRevision:
    new_source = source_id is None
    source_id = await _ensure_source(db, project_id=project_id, source_id=source_id, source_key=source_key,
                                     display_title=display_title, created_by=created_by)
    revision_ordinal = await _next_ordinal(db, project_id, source_id)
    revision_id = new_revision_id()
    digest = stored.ref.content_sha256
    if type(digest) is not str:
        raise EvidenceLedgerContractError()
    _add_revision_and_spans(db, project_id=project_id, source_id=source_id, revision_id=revision_id,
                            revision_ordinal=revision_ordinal, digest=digest, display_title=display_title,
                            media_type=media_type, stored=stored, spans=spans,
                            parser=(parser_name, parser_version, parser_sandbox))
    # Order boundary, not a transaction boundary. The outbox entry's ``revision_id`` foreign key is
    # not declared as a relationship, so the unit of work has no dependency to sort on and is free to
    # emit the outbox insert first; PostgreSQL checks the foreign key per statement and rejects it,
    # while SQLite with foreign keys off never sees it. Flushing the revision and its spans here makes
    # the order explicit while everything stays in the one uncommitted transaction below.
    try:
        await db.flush()
    except IntegrityError:
        raise _RevisionInsertConflictError(stage=_STAGE_REVISION, attempted_ordinal=revision_ordinal) from None
    _add_revision_details(db, project_id=project_id, revision_id=revision_id, spans=spans, source_url=source_url,
                          source_changed_at=source_changed_at, products=products, version=version)
    await _owe_first_operation(db, project_id=project_id, source_id=source_id, revision_id=revision_id,
                               new_source=new_source, first_operation=first_operation)
    # One transaction: the revision, its spans, and its projection obligation.
    try:
        await db.commit()
    except IntegrityError:
        raise _RevisionInsertConflictError(stage=_STAGE_REVISION, attempted_ordinal=revision_ordinal) from None
    logger.info(
        "Knowledge evidence revision registered: ordinal=%d spans=%d workspace=%s",
        revision_ordinal,
        len(spans),
        project_id,
    )
    return RegisteredRevision(source_id=source_id, revision_id=revision_id, revision_ordinal=revision_ordinal,
                              content_sha256=digest, span_count=len(spans), created=True)


