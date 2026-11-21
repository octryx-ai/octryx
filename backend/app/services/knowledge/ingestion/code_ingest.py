"""Workspace-authorized ingestion of one repository file as a code revision.

The one ingestion path of every ``git_repository`` fetch mode (the host archive and a launcher's
local snapshot), so the same file yields the same revision either way. It follows the order of
``text_ingest.py``: everything that can refuse runs before any byte is written.

1. The bytes are bounded (``MAX_TEXT_BYTES``) and must be text-native by a binary sniff.
2. They are decoded as strict UTF-8, and secrets are redacted line by line
   (``code/redaction.py``), so no line moves and every cited range stays the repository's range.
3. The normalized text is split into code-aware spans with line ranges (``code/chunking.py``).
4. Only then is the redacted text written and the revision registered; each span gets a locator
   row of kind ``code`` with its line range, which citations turn into ``#L<start>-L<end>``.

The stored bytes are the redacted text, so a revision never holds a secret the redaction found.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..code.chunking import derive_code_spans
from ..code.redaction import redact_repository_text
from ..ledger.revisions import register_revision
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from ..sources.source_url import normalize_source_url
from .media_types import PARSER_SANDBOX, resolve_text_native_media_type
from .publication import publish_object
from .spans import decode_text, normalize_display_title, normalize_source_key
from .text_ingest import MAX_TEXT_BYTES, IngestedSource, check_ingest_payload, ingested_source

logger = logging.getLogger(__name__)

CODE_PARSER_NAME = "code_chunker"
CODE_PARSER_VERSION = "2"
CODE_MEDIA_TYPE = "text/plain"


async def ingest_code_source(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    source_key: object,
    display_title: object,
    data: bytes,
    created_by: str | None,
    source_url: object = None,
    source_changed_at: datetime | None = None,
    products: object = None,
    version: object = None,
    language: str | None = None,
    path: str | None = None,
) -> IngestedSource:
    """Ingest one repository file into an immutable Workspace revision with line-ranged spans.

    ``path`` is the repository path; a configuration file also loses its secret-named setting values.
    """
    check_ingest_payload(runtime, authorized, data, MAX_TEXT_BYTES)
    key = normalize_source_key(source_key)
    title = normalize_display_title(display_title)
    origin = normalize_source_url(source_url)
    scope_products = normalize_products(products)
    scope_version = normalize_version(version)
    media_type = resolve_text_native_media_type(CODE_MEDIA_TYPE, data)
    redacted = redact_repository_text(decode_text(data), path)
    spans = derive_code_spans(redacted.text, language)

    stored = await publish_object(db, runtime=runtime, authorized=authorized, data=redacted.text.encode("utf-8"))
    revision = await register_revision(
        db,
        authorized=authorized,
        source_key=key,
        display_title=title,
        media_type=media_type,
        stored=stored,
        spans=spans,
        parser_name=CODE_PARSER_NAME,
        parser_version=CODE_PARSER_VERSION,
        parser_sandbox=PARSER_SANDBOX,
        created_by=created_by,
        source_url=origin,
        source_changed_at=source_changed_at,
        products=scope_products,
        version=scope_version,
    )
    logger.info(
        "Knowledge code file ingested: created=%s spans=%d redactions=%d workspace=%s",
        revision.created,
        revision.span_count,
        redacted.redactions,
        authorized.project_id,
    )
    return ingested_source(revision, stored, key, media_type)


def prepared_code_text(data: bytes, path: str | None = None) -> str:
    """The text a code revision stores for ``data``: normalized and redacted, lines unchanged.

    The repository file index derives its code elements from exactly this text
    (``code/repository_index.upsert_file``), so its lines are the cited lines.
    """
    return redact_repository_text(decode_text(data), path).text


__all__ = ["CODE_PARSER_NAME", "CODE_PARSER_VERSION", "ingest_code_source", "prepared_code_text"]
