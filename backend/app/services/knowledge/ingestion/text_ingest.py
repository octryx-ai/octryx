"""Workspace-authorized ingestion of one text-native source revision.

Refusal order is part of the contract. Everything that can refuse the
payload runs **before** any byte is written to object storage:

1. the Workspace is already authorized by the caller (an ``AuthorizedWorkspace``
   is the only accepted scope — this function cannot be called with a raw id);
2. the source key and title are normalized and bounded;
3. the media type must be text-native by *both* the declared type and a binary
   sniff of the leading bytes;
4. the payload is decoded as strict UTF-8 and split into spans.

Only then is the object written, content-addressed and Workspace-partitioned, and
only then is the ledger row plus its outbox entry committed. So an unsupported or
undecodable upload leaves no object, no row, and no projection obligation behind.

Nothing here spawns a subprocess or touches the host filesystem, and nothing is
dispatched with ``asyncio.create_task``: the committed outbox entry *is* the
handoff to the projector.

Because the object is written before the revision commits, the reverse is also true: the
operator-owned retention pass may already have decided to delete exactly this object.
Two things guard that, and only the first of them is a guarantee:

1. **The publication boundary.** The content address is derived *before* the write, and the
   transaction-scoped advisory lock on ``(Workspace, object key)`` is taken before it too, so
   the write and the commit of the reference are one critical section that a retention pass
   in another process cannot interleave with
   (``services/knowledge/object_publication_lock.py``). A pass that already holds the key
   makes this ingestion wait inside the database, and then it writes the object again at the
   same content address, so its reference is valid either way.
2. **The hold.** A committed retention hold on the key is a fast, explicit refusal: this
   ingestion answers the retryable ``unavailable`` state instead of waiting for an operator
   pass to finish its settle window. The next attempt succeeds once the hold is gone.

The cost of the first one is stated rather than hidden: the database transaction is open
across the object write, so one PostgreSQL connection is held for the duration of an upload of
at most ``MAX_UPLOAD_BYTES``, bounded by the object client's own connect/read timeouts. The
alternative — taking the boundary after the write — leaves exactly the interleaving the boundary
prevents, because the bytes would already be there when the pass measured them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import EvidenceLedgerContractError, EvidencePayloadTooLargeError, InvalidEvidenceRequestError
from ..ledger.revisions import RegisteredRevision, register_revision
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
    """What one ingestion produced; ``created`` is False for identical bytes."""

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
    """The refusals every ingestion makes first: an unscoped call, an empty payload, an oversized one."""
    if type(runtime) is not EvidenceRuntime or type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    if type(data) is not bytes or not data:
        raise InvalidEvidenceRequestError()
    if len(data) > max_bytes:
        raise EvidencePayloadTooLargeError()


def ingested_source(revision: RegisteredRevision, stored: StoredObject, key: str, media_type: str) -> IngestedSource:
    """What one ingestion reports for its registered revision and stored object."""
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
    """Ingest one text-native payload into an immutable Workspace revision."""
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
