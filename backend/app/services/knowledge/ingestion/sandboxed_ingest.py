"""Workspace-authorized ingestion of one PDF or Office revision. Everything that can refuse runs first; the API process
never parses these bytes."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..ledger.errors import EvidenceParserNotConfiguredError
from ..ledger.revisions import register_revision
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from ..sources.source_url import normalize_source_url
from .media_types import resolve_sandboxed_media_type
from .ocr_choice import registered_version
from .publication import publish_object
from .spans import normalize_display_title, normalize_source_key
from .text_ingest import MAX_UPLOAD_BYTES, IngestedSource, check_ingest_payload, ingested_source

logger = logging.getLogger(__name__)


async def ingest_sandboxed_source(
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
    check_ingest_payload(runtime, authorized, data, MAX_UPLOAD_BYTES)

    key = normalize_source_key(source_key)
    title = normalize_display_title(display_title)
    origin = normalize_source_url(source_url)
    scope_products = normalize_products(products)
    scope_version = normalize_version(version)
    media_type = resolve_sandboxed_media_type(declared_media_type, data)
    if runtime.parser is None:
        raise EvidenceParserNotConfiguredError()
    identity = runtime.parser.identity

    stored = await publish_object(db, runtime=runtime, authorized=authorized, data=data)
    revision = await register_revision(
        db,
        authorized=authorized,
        source_key=key,
        display_title=title,
        media_type=media_type,
        stored=stored,
        spans=(),
        parser_name=identity.name,
        parser_version=registered_version(identity.version, media_type),  # a PDF's OCR is decided at parse
        parser_sandbox=identity.sandbox,
        created_by=created_by,
        source_url=origin,
        source_changed_at=source_changed_at,
        products=scope_products,
        version=scope_version,
        pending_parse=True,
    )
    logger.info(
        "Knowledge evidence registered for the parser sandbox: created=%s workspace=%s",
        revision.created,
        authorized.project_id,
    )
    return ingested_source(revision, stored, key, media_type)


__all__ = ["ingest_sandboxed_source"]
