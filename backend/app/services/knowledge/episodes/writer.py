"""Write one session episode summary as a governed source revision.

The order is the contract:

1. **Who.** The Workspace is already authorized by the caller (an ``AuthorizedWorkspace`` read
   directly, never through a binding), and the caller's role must be a writer role; else ``denied``.
2. **Whether.** The Workspace must accept session episodes and the platform's public origin must be
   configured (``policy.py``); else ``needs_configuration``.
3. **What.** The summary is bounded (``MAX_EPISODE_CHARS``), must be visible text, and is redacted by
   the shared redaction core (``redaction.py``) before anything is written.
4. **Where.** The normal text ingestion writes the object, the revision, its spans and its projection
   outbox entry in one transaction, so the episode becomes searchable and graph-extractable like any
   source. Its origin link is the session in the platform UI.

**Identity and deduplication.** The source key is ``session-episode.<session id>``, so one session is
one source. A summary whose digest that session's source already holds is answered as ``duplicate``
with the existing revision before anything is written (the ledger's unique ``(source, content
digest)`` backs this up under a race), while a changed summary of the same session is its next
revision. Two sessions never share a source.

**Classification.** A source has no classification of its own: the episode is governed by its
Workspace's data classification, like every other source there. It carries no source ACL, so every
member of the Workspace can read it.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevision
from ..access.authorization import AuthorizedWorkspace, WorkspaceWriteForbiddenError
from ..ingestion.text_ingest import ingest_text_source
from ..ledger.errors import EvidenceLedgerError
from ..retrieval.locator import markdown_citation
from ..runtime import get_evidence_runtime
from ..text_safety import has_unsafe_chars, remove_unsafe_chars
from .policy import EPISODE_WRITER_ROLES, episodes_accepted, public_origin, session_link
from .redaction import redact_episode_text

SOURCE_KEY_PREFIX = "session-episode."
MAX_EPISODE_CHARS = 8000
MAX_TITLE_CHARS = 120
MAX_CLIENT_CHARS = 60
MEDIA_TYPE = "text/markdown"

REFUSALS: dict[str, tuple[str, str]] = {
    "role_required": ("denied", "Returning a session episode needs a member, admin or owner role in the Workspace."),
    "episodes_disabled": (
        "needs_configuration",
        "This Workspace does not accept session episodes. A Workspace admin or owner can enable them.",
    ),
    "public_origin_missing": (
        "needs_configuration",
        "The platform's public origin is not configured, so an episode citation could not link to its session.",
    ),
    "invalid_summary": ("invalid_request", "The summary was empty, not visible text, or not a string."),
    "summary_too_long": ("limit_exceeded", f"The summary exceeds {MAX_EPISODE_CHARS} characters."),
    "invalid_session": ("invalid_request", "The session reference is not valid."),
}
LEDGER_MESSAGES = {
    "invalid_request": "The episode's title, products or version are outside the supported bounds.",
    "needs_configuration": "This Workspace has no Knowledge evidence store yet.",
    "unavailable": "The Knowledge evidence store is currently unavailable.",
    "limit_exceeded": "The episode exceeds a supported bound.",
}
FALLBACK_MESSAGE = "The Knowledge evidence store could not record this episode."


@dataclass(frozen=True, slots=True)
class EpisodeProvenance:
    """Where an episode came from, resolved by the server; never from a model argument."""

    session_id: str
    client: str
    recorded_by: str
    session_date: str


def refusal(reason: str) -> dict[str, str]:
    state, message = REFUSALS[reason]
    return {"state": state, "reason": reason, "error": message}


def _ledger_refusal(error: EvidenceLedgerError) -> dict[str, str]:
    state = error.state.value
    return {"state": state, "reason": state, "error": LEDGER_MESSAGES.get(state, FALLBACK_MESSAGE)}


def _one_line(raw: object, limit: int) -> str:
    text = " ".join(remove_unsafe_chars(str(raw or ""), allow_line_breaks=False).split())
    return text[:limit].strip()


def _canonical_session_id(raw: object) -> str | None:
    try:
        return str(uuid.UUID(str(raw)))
    except ValueError:
        return None


def episode_title(provenance: EpisodeProvenance, title: object) -> str:
    label = _one_line(title, MAX_TITLE_CHARS) or f"{provenance.session_date} session"
    client = _one_line(provenance.client, MAX_CLIENT_CHARS) or "session"
    return f"Session episode ({client}): {label}"


async def episode_refusal(db: AsyncSession, authorized: AuthorizedWorkspace, summary: object) -> dict[str, str] | None:
    """Steps 1 to 3: the refusal for this caller, Workspace and summary, or ``None`` when it may be written.

    Callers that must create something first (an MCP shadow session) ask this before they do.
    """
    if authorized.on_behalf_of is not None or authorized.role not in EPISODE_WRITER_ROLES:
        return refusal("role_required")
    if not await episodes_accepted(db, authorized.project_id):
        return refusal("episodes_disabled")
    if public_origin() is None:
        return refusal("public_origin_missing")
    if type(summary) is not str or not summary.strip() or has_unsafe_chars(summary, allow_line_breaks=True):
        return refusal("invalid_summary")
    if len(summary.strip()) > MAX_EPISODE_CHARS:
        return refusal("summary_too_long")
    return None


async def _ingest(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    provenance: EpisodeProvenance,
    answer: dict[str, object],
    display_title: str,
    data: bytes,
    products: object,
    version: object,
) -> dict[str, object]:
    """Step 4: the text ingestion writes the revision; a ledger refusal is answered as a fixed state."""
    try:
        ingested = await ingest_text_source(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            source_key=answer["source_key"],
            display_title=display_title,
            declared_media_type=MEDIA_TYPE,
            data=data,
            created_by=provenance.recorded_by,
            source_url=answer["source_url"],
            products=products,
            version=version,
        )
    except EvidenceLedgerError as error:
        return _ledger_refusal(error)
    except WorkspaceWriteForbiddenError:
        # A concurrent write of the same summary won the race and the ledger asked the loser to
        # requeue its projection, which only an author may. Retrying answers ``duplicate``.
        return {"state": "unavailable", "reason": "unavailable", "error": LEDGER_MESSAGES["unavailable"]}
    return {
        "state": "recorded" if ingested.created else "duplicate",
        **answer,
        "revision_id": ingested.revision_id,
        "revision": ingested.revision_ordinal,
        "span_count": ingested.span_count,
        # A new revision owes its projection; a duplicate changes nothing.
        "projection": "pending" if ingested.created else "unchanged",
    }


async def record_episode_summary(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    provenance: EpisodeProvenance,
    summary: object,
    title: object = None,
    products: object = None,
    version: object = None,
) -> dict[str, object]:
    """Record the summary; the caller commits. Every refusal is a fixed state with a fixed message."""
    refused = await episode_refusal(db, authorized, summary)
    if refused is not None:
        return refused
    origin = public_origin() or ""
    session_id = _canonical_session_id(provenance.session_id)
    if session_id is None:
        return refusal("invalid_session")
    redacted = redact_episode_text(str(summary).strip())
    display_title = episode_title(provenance, title)
    link = session_link(origin, session_id)
    source_key = f"{SOURCE_KEY_PREFIX}{session_id}"
    data = (redacted.text + "\n").encode("utf-8")
    answer = {
        "workspace_id": authorized.project_id,
        "session_id": session_id,
        "source_key": source_key,
        "redactions": redacted.redactions,
        "source_url": link,
        "cite_as": markdown_citation(display_title, link, ()),
    }
    existing = await _existing_revision(db, authorized.project_id, source_key, hashlib.sha256(data).hexdigest())
    if existing is not None:
        revision_id, ordinal, span_count = existing
        return {
            "state": "duplicate",
            **answer,
            "revision_id": revision_id,
            "revision": ordinal,
            "span_count": span_count,
            "projection": "unchanged",
        }
    return await _ingest(
        db,
        authorized=authorized,
        provenance=provenance,
        answer=answer,
        display_title=display_title,
        data=data,
        products=products,
        version=version,
    )


async def _existing_revision(
    db: AsyncSession, project_id: str, source_key: str, digest: str
) -> tuple[str, int, int] | None:
    row = (
        await db.execute(
            select(
                KnowledgeSourceRevision.id,
                KnowledgeSourceRevision.revision_ordinal,
                KnowledgeSourceRevision.span_count,
            )
            .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
            .where(
                KnowledgeEvidenceSource.project_id == project_id,
                KnowledgeSourceRevision.project_id == project_id,
                KnowledgeEvidenceSource.source_key == source_key,
                KnowledgeSourceRevision.content_sha256 == digest,
            )
            .limit(1)
        )
    ).first()
    return None if row is None else (str(row[0]), int(row[1]), int(row[2] or 0))


__all__ = [
    "MAX_EPISODE_CHARS",
    "SOURCE_KEY_PREFIX",
    "EpisodeProvenance",
    "episode_refusal",
    "episode_title",
    "record_episode_summary",
    "refusal",
]
