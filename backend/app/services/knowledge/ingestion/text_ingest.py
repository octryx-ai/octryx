"""Workspace-authorized ingestion of one text-native source revision. Everything that can refuse runs before any byte is
written to object storage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import EvidenceLedgerContractError, EvidencePayloadTooLargeError, InvalidEvidenceRequestError
from ..ledger.revision_races import RegisteredRevision
from ..ledger.revisions import register_revision
from ..objects import MAX_OBJECT_BYTES, StoredObject
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from ..sources.source_url import normalize_source_url
from .media_types import PARSER_NAME, PARSER_SANDBOX, PARSER_VERSION, resolve_text_native_media_type
from .publication import publish_object
from .spans import decode_text, derive_spans, normalize_display_title, normalize_source_key
from .text_outline import OUTLINE_PARSER_VERSION, derive_outlined_spans, has_outline

logger = logging.getLogger(__name__)

# The route's bound on any upload; sandboxed documents may use all of it.
MAX_UPLOAD_BYTES = MAX_OBJECT_BYTES
# Text-native documents are parsed in this process, so they keep the tighter bound.
MAX_TEXT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class IngestedSource:
    source_id: str
    source_key: str
    revision_id: str
    revision_ordinal: int
    content_sha256: str
    media_type: str
    byte_size: int
    span_count: int
    created: bool
    object_created: bool


def check_ingest_payload(runtime: object, authorized: object, data: object, max_bytes: int) -> None:
    if type(runtime) is not EvidenceRuntime or type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    if type(data) is not bytes or not data:
        raise InvalidEvidenceRequestError()
    if len(data) > max_bytes:
        raise EvidencePayloadTooLargeError()


def ingested_source(revision: RegisteredRevision, stored: StoredObject, key: str, media_type: str) -> IngestedSource:
    return IngestedSource(
        source_id=revision.source_id,
        source_key=key,
        revision_id=revision.revision_id,
        revision_ordinal=revision.revision_ordinal,
        content_sha256=revision.content_sha256,
        media_type=media_type,
        byte_size=stored.byte_size,
        span_count=revision.span_count,
        created=revision.created,
        object_created=stored.created,
    )


async def ingest_text_source(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    source_key: object,
    display_title: object,
    declared_media_type: object,
    data: bytes,
    created_by: str | None,
    source_url: object = None,
    source_changed_at: datetime | None = None,
    products: object = None,
    version: object = None,
) -> IngestedSource:
    check_ingest_payload(runtime, authorized, data, MAX_TEXT_BYTES)

    key = normalize_source_key(source_key)
    title = normalize_display_title(display_title)
    origin = normalize_source_url(source_url)
    scope_products = normalize_products(products)
    scope_version = normalize_version(version)
    # Refuses a PDF, Office document, or image here, before anything is written.
    media_type = resolve_text_native_media_type(declared_media_type, data)
    text = decode_text(data)
    # Markdown and AsciiDoc with headings: spans follow the headings. Everything else (and a heading-
    # less Markdown note) splits by paragraph.
    outlined = has_outline(text, media_type)
    spans = derive_outlined_spans(text, media_type) if outlined else derive_spans(text)

    # The transaction stays open across the object write, holding one database connection for the upload: taking the
    # publication lock after the write would let a retention pass measure the bytes in between.
    stored = await publish_object(db, runtime=runtime, authorized=authorized, data=data)

    revision: RegisteredRevision = await register_revision(
        db,
        authorized=authorized,
        source_key=key,
        display_title=title,
        media_type=media_type,
        stored=stored,
        spans=spans,
        parser_name=PARSER_NAME,
        parser_version=OUTLINE_PARSER_VERSION if outlined else PARSER_VERSION,
        parser_sandbox=PARSER_SANDBOX,
        created_by=created_by,
        source_url=origin,
        source_changed_at=source_changed_at,
        products=scope_products,
        version=scope_version,
    )
    logger.info(
        "Knowledge evidence ingested: created=%s spans=%d workspace=%s",
        revision.created,
        revision.span_count,
        authorized.project_id,
    )
    return ingested_source(revision, stored, key, media_type)
