"""Display one revision's original as sanitized HTML and plain text. Authorization is exactly the original route's; its
refusals pass through unchanged."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeSourceRevisionOrigin
from ....time_utils import ensure_utc
from ..access.authorization import AuthorizedWorkspace
from ..ingestion.media_types import TEXT_NATIVE_MEDIA_TYPES
from ..ledger.original import OriginalContent, read_original
from ..ledger.original_errors import OriginalNotDisplayableError
from ..runtime import EvidenceRuntime
from ..text_safety import remove_unsafe_chars
from .html_view import render_html_view

MAX_VIEW_BYTES = 4 * 1024 * 1024
HTML_MEDIA_TYPE = "text/html"
TEXT_MEDIA_TYPES = frozenset(TEXT_NATIVE_MEDIA_TYPES.values())

STATE_OK = "ok"
STATE_TOO_LARGE = "too_large"


@dataclass(frozen=True, slots=True)
class DisplayText:
    text: str
    html: str | None


@dataclass(frozen=True, slots=True)
class RevisionOrigin:
    source_url: str | None
    source_changed_at: str | None


def is_displayable(media_type: str) -> bool:
    return media_type == HTML_MEDIA_TYPE or media_type in TEXT_MEDIA_TYPES


def _decoded(data: bytes) -> str:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        decoded = None
    if decoded is None:
        # Raised outside the handler so the decode error is not chained.
        raise OriginalNotDisplayableError()
    normalized = decoded.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return remove_unsafe_chars(normalized, allow_line_breaks=True)


def display_text(original: OriginalContent) -> DisplayText:
    if not is_displayable(original.media_type):
        raise OriginalNotDisplayableError()
    decoded = _decoded(original.data)
    if original.media_type == HTML_MEDIA_TYPE:
        view = render_html_view(decoded)
        return DisplayText(text=view.text, html=view.html)
    return DisplayText(text=decoded, html=None)


async def revision_origin(db: AsyncSession, authorized: AuthorizedWorkspace, revision_id: str) -> RevisionOrigin:
    row = (
        await db.execute(
            select(KnowledgeSourceRevisionOrigin.source_url, KnowledgeSourceRevisionOrigin.source_changed_at).where(
                KnowledgeSourceRevisionOrigin.project_id == authorized.project_id,
                KnowledgeSourceRevisionOrigin.revision_id == revision_id,
            )
        )
    ).first()
    if row is None:
        return RevisionOrigin(source_url=None, source_changed_at=None)
    changed = row[1]
    return RevisionOrigin(
        source_url=row[0] or None,
        source_changed_at=ensure_utc(changed).isoformat() if changed is not None else None,
    )


async def read_original_view(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    source_id: str,
    revision_id: str,
) -> dict:
    original = await read_original(
        db, runtime=runtime, authorized=authorized, source_id=source_id, revision_id=revision_id
    )
    if not is_displayable(original.media_type):
        raise OriginalNotDisplayableError()
    origin = await revision_origin(db, authorized, revision_id)
    too_large = len(original.data) > MAX_VIEW_BYTES
    shown = None if too_large else display_text(original)
    return {
        "workspace_id": authorized.project_id,
        "source_id": source_id,
        "revision_id": revision_id,
        "revision_ordinal": original.revision_ordinal,
        "content_type": original.media_type,
        "content_sha256": original.content_sha256,
        "byte_size": len(original.data),
        "source_url": origin.source_url,
        "source_changed_at": origin.source_changed_at,
        "state": STATE_TOO_LARGE if too_large else STATE_OK,
        "limit_bytes": MAX_VIEW_BYTES,
        "html": shown.html if shown else None,
        "text": shown.text if shown else None,
    }


__all__ = [
    "MAX_VIEW_BYTES",
    "DisplayText",
    "RevisionOrigin",
    "display_text",
    "is_displayable",
    "read_original_view",
    "revision_origin",
]
