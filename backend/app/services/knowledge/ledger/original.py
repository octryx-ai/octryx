"""Read the original bytes of one source revision, for a person to open.

The ledger keeps every revision's bytes in the Workspace's object partition. This module is the
only path from the API to those bytes, and it adds nothing a reader could not already see through
source detail: the same Workspace predicate, the same per-source ACL (:func:`visible_source`), and a
digest-verified read bounded by ``MAX_OBJECT_BYTES``.

Indistinguishable refusals. A revision of another Workspace, an unknown revision, a revision of a
source the caller's ACL hides, and a tombstoned revision all raise the same
:class:`EvidenceRecordNotFoundError`, so the route cannot be used to probe which documents exist.

Precise refusals once the revision is known to be readable (``original_errors``): no object recorded
for it, a recorded key outside this deployment's partition, and an object absent in the store each
have their own class, so a missing object never reads like an unknown Workspace again.

Nothing about storage leaves this module: the bucket, the object key and the version id are read
to address the object and are never returned. There is no presigned URL; the bytes are proxied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    REVISION_STATE_TOMBSTONED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
)
from ..access.authorization import AuthorizedWorkspace
from ..access.source_acl import visible_source
from ..objects import (
    MAX_OBJECT_BYTES,
    KnowledgeObjectError,
    KnowledgeObjectIntegrityError,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectNotFoundError,
    KnowledgeObjectOutsidePartitionError,
    KnowledgeObjectTooLargeError,
)
from ..objects.source_object import SourceObjectRef
from ..retrieval.errors import KnowledgeRetrievalError
from ..runtime import EvidenceRuntime
from .errors import (
    EvidenceLedgerContractError,
    EvidencePayloadTooLargeError,
    EvidenceRecordNotFoundError,
    EvidenceStoreNotConfiguredError,
    EvidenceStoreUnavailableError,
)
from .original_errors import OriginalLocationMismatchError, OriginalNotStoredError, OriginalObjectMissingError

MAX_ID_CHARS = 36
MAX_FILENAME_STEM_CHARS = 80

# The one media type a browser may render inline; everything else is a download.
INLINE_MEDIA_TYPES = frozenset({"application/pdf"})

# The original is untrusted content: never sniffed, never scripted, never cached, never embedded elsewhere.
ORIGINAL_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
    "Cache-Control": "private, no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
}

_EXTENSION_BY_MEDIA_TYPE = {
    "text/plain": "txt",
    "text/markdown": "md",
    "text/asciidoc": "adoc",
    "text/csv": "csv",
    "text/html": "html",
    "application/json": "json",
    "application/xml": "xml",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class OriginalContent:
    """The verified bytes of one revision and how to present them; no storage location."""

    data: bytes
    media_type: str
    filename: str
    inline: bool
    content_sha256: str
    revision_ordinal: int = 0


def original_headers(original: OriginalContent) -> dict[str, str]:
    """Response headers for serving one original; the filename is already ASCII-safe."""
    disposition = "inline" if original.inline else "attachment"
    return {
        **ORIGINAL_RESPONSE_HEADERS,
        "Content-Disposition": f'{disposition}; filename="{original.filename}"',
        "X-Content-SHA256": original.content_sha256,
    }


def safe_filename(display_title: object, revision_ordinal: int, media_type: str) -> str:
    """An ASCII-only download name derived from the title, never from the uploaded file name."""
    stem = _UNSAFE_FILENAME_CHARS.sub("-", str(display_title or "")).strip(".-_")[:MAX_FILENAME_STEM_CHARS]
    stem = stem.strip(".-_") or "source"
    extension = _EXTENSION_BY_MEDIA_TYPE.get(media_type, "bin")
    return f"{stem}-r{int(revision_ordinal)}.{extension}"


def _is_recorded(value: object) -> bool:
    """A ledger location column that names something; empty means no original was kept."""
    return type(value) is str and bool(value.strip())


def _is_id(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= MAX_ID_CHARS


async def _locate(db: AsyncSession, authorized: AuthorizedWorkspace, source_id: str, revision_id: str):
    project_id = authorized.project_id
    return (
        await db.execute(
            select(
                KnowledgeSourceRevision.object_bucket,
                KnowledgeSourceRevision.object_key,
                KnowledgeSourceRevision.object_version_id,
                KnowledgeSourceRevision.content_sha256,
                KnowledgeSourceRevision.media_type,
                KnowledgeSourceRevision.byte_size,
                KnowledgeSourceRevision.revision_ordinal,
                KnowledgeEvidenceSource.display_title,
            )
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .where(
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeSourceRevision.source_id == source_id,
                KnowledgeSourceRevision.id == revision_id,
                # A removed source is out of the served Knowledge; its bytes are not served either.
                KnowledgeSourceRevision.state != REVISION_STATE_TOMBSTONED,
                visible_source(project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
            )
        )
    ).first()


async def _verified_bytes(runtime: EvidenceRuntime, authorized: AuthorizedWorkspace, ref: SourceObjectRef) -> bytes:
    failure: Exception | None = None
    try:
        return await runtime.object_store.get_verified(authorized.workspace, ref)
    except KnowledgeObjectOutsidePartitionError:
        failure = OriginalLocationMismatchError()
    except KnowledgeObjectNotFoundError:
        failure = OriginalObjectMissingError()
    except KnowledgeObjectNotConfiguredError:
        failure = EvidenceStoreNotConfiguredError()
    except KnowledgeObjectTooLargeError:
        failure = EvidencePayloadTooLargeError()
    except KnowledgeObjectIntegrityError:
        # Bytes that do not hash to their address are never served.
        failure = EvidenceLedgerContractError()
    except KnowledgeObjectError:
        failure = EvidenceStoreUnavailableError()
    # Raised outside the handler so no object-store error is chained as context.
    raise failure


async def read_original(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    source_id: object,
    revision_id: object,
) -> OriginalContent:
    """The digest-verified original bytes of one visible revision, or the not-found state."""
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    if not _is_id(source_id) or not _is_id(revision_id):
        raise EvidenceRecordNotFoundError()
    row = await _locate(db, authorized, source_id, revision_id)
    if row is None:
        raise EvidenceRecordNotFoundError()
    bucket, key, version_id, digest, media_type, byte_size, ordinal, title = row
    if not _is_recorded(bucket) or not _is_recorded(key):
        raise OriginalNotStoredError()
    if int(byte_size) > MAX_OBJECT_BYTES:
        raise EvidencePayloadTooLargeError()
    try:
        ref = SourceObjectRef(bucket=bucket, key=key, version_id=version_id, content_sha256=digest)
    except KnowledgeRetrievalError:
        ref = None
    if ref is None:
        # A stored reference outside its own contract is a ledger inconsistency, not a missing record.
        raise EvidenceLedgerContractError()
    data = await _verified_bytes(runtime, authorized, ref)
    if len(data) != int(byte_size):
        raise EvidenceLedgerContractError()
    return OriginalContent(
        data=data,
        media_type=media_type,
        filename=safe_filename(title, ordinal, media_type),
        inline=media_type in INLINE_MEDIA_TYPES,
        content_sha256=digest,
        revision_ordinal=int(ordinal),
    )


__all__ = [
    "INLINE_MEDIA_TYPES",
    "ORIGINAL_RESPONSE_HEADERS",
    "OriginalContent",
    "original_headers",
    "read_original",
    "safe_filename",
]
