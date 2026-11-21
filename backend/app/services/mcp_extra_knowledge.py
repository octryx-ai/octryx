"""``knowledge_sources`` and ``knowledge_feedback`` on the Knowledge MCP (handlers for ``run_parity_mcp_tool``).

The runner has already checked the scope, the user, the rate limit and the connection Workspace
(authorized for the user). The handlers never read a Workspace or a user from their arguments.

- ``knowledge_sources`` lists the Workspace's Evidence ledger sources like ``GET /api/v1/workspaces/
  {id}/knowledge/sources`` (``knowledge/ledger/queries.list_sources``): Workspace-filtered, source
  ACL re-checked for the caller's principals, newest first, bounded. It adds paging (``offset``) and
  each source's current revision with its origin link (``source_url``) and ready ``cite_as``.
- ``knowledge_feedback`` rates an Octryx answer exactly like the chat's thumbs
  (``session/feedback.submit_session_message_feedback``: closed values, bounded texts, secrets
  refused, one record per person and answer). The session must belong to the caller and to the
  connection Workspace. The texts reach only the Memory lobe; the activity row and the audit keep no
  argument value, only the outcome state.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import ConflictError
from app.exceptions.base import NotFoundError

from ..models import Session, User
from ..models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from .knowledge.access.authorization import authorize_tool_workspace
from .knowledge.access.source_acl import visible_source
from .knowledge.ledger.errors import EvidenceLedgerError
from .knowledge.ledger.queries import DEFAULT_SOURCE_LIMIT, MAX_SOURCE_LIMIT
from .knowledge.retrieval.locator import markdown_citation
from .mcp_extra_scope import refusal
from .session.feedback import SessionFeedbackRefusedError, submit_session_message_feedback

MAX_OFFSET = 10_000
_MAX_ID_CHARS = 64

INVALID_PAGE = refusal(
    "invalid_request", "invalid_page", f"limit must be 1-{MAX_SOURCE_LIMIT} and offset 0-{MAX_OFFSET}."
)
NOT_FOUND = refusal("not_found", "answer_not_found", "No such answer of yours in this Workspace.")
ASSISTANT_ONLY = refusal("invalid_request", "assistant_messages_only", "Only assistant answers can be rated.")
FEEDBACK_MESSAGES = {
    "invalid_request": "The feedback is outside its closed values (rating good|bad, known aspects).",
    "invalid_text": "A feedback text is too long or contains characters that are not allowed.",
    "secret_detected": "A feedback text looks like it contains a credential; nothing was recorded.",
    "workspace_required": "This answer's chat has no Workspace to keep feedback in.",
    "workspace_not_accessible": "No such answer of yours in this Workspace.",
}


def _bounded_int(value: object, default: int, low: int, high: int) -> int | None:
    if value is None:
        return default
    if type(value) is not int or not low <= value <= high:
        return None
    return value


async def _newest_ordinals(db: AsyncSession, project_id: str, source_ids: list[str], *, projected: bool) -> dict:
    conditions = [KnowledgeSourceRevision.project_id == project_id, KnowledgeSourceRevision.source_id.in_(source_ids)]
    if projected:
        conditions.append(KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED)
    statement = (
        select(KnowledgeSourceRevision.source_id, func.max(KnowledgeSourceRevision.revision_ordinal))
        .where(*conditions)
        .group_by(KnowledgeSourceRevision.source_id)
    )
    return {source_id: ordinal for source_id, ordinal in (await db.execute(statement)).all()}


async def _current_revisions(db: AsyncSession, project_id: str, source_ids: list[str]) -> dict[str, tuple]:
    """Per source: its current revision (the newest projected one, else the newest) and its origin link."""
    if not source_ids:
        return {}
    chosen = {
        **(await _newest_ordinals(db, project_id, source_ids, projected=False)),
        **(await _newest_ordinals(db, project_id, source_ids, projected=True)),
    }
    if not chosen:
        return {}
    revision, origin = KnowledgeSourceRevision, KnowledgeSourceRevisionOrigin
    rows = (
        await db.execute(
            select(revision.source_id, revision.revision_ordinal, revision.state, origin.source_url)
            .outerjoin(
                origin,
                (origin.revision_id == revision.id)
                & (origin.project_id == project_id),
            )
            .where(
                revision.project_id == project_id,
                or_(
                    *(
                        and_(revision.source_id == source_id, revision.revision_ordinal == ordinal)
                        for source_id, ordinal in chosen.items()
                    )
                ),
            )
            .limit(len(chosen))
        )
    ).all()
    return {source_id: (ordinal, state, url) for source_id, ordinal, state, url in rows}


async def mcp_knowledge_sources(
    db: AsyncSession, *, caller: Any, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    limit = _bounded_int(arguments.get("limit"), DEFAULT_SOURCE_LIMIT, 1, MAX_SOURCE_LIMIT)
    offset = _bounded_int(arguments.get("offset"), 0, 0, MAX_OFFSET)
    if limit is None or offset is None:
        return dict(INVALID_PAGE)
    try:
        authorized = await authorize_tool_workspace(
            db, user_id=str(user.id), project_id=workspace_id, allowed_project_ids=[workspace_id]
        )
    except EvidenceLedgerError:
        return refusal("not_found", "workspace_not_found", "No Knowledge workspace is in scope for this session.")
    visible = (
        KnowledgeEvidenceSource.project_id == authorized.project_id,
        visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
    )
    total = int((await db.execute(select(func.count(KnowledgeEvidenceSource.id)).where(*visible))).scalar_one())
    source = KnowledgeEvidenceSource
    page = (
        await db.execute(
            select(source.id, source.source_key, source.display_title)
            .where(*visible)
            .order_by(source.created_at.desc(), source.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    revisions = await _current_revisions(db, authorized.project_id, [row[0] for row in page])
    sources = []
    for source_id, source_key, title in page:
        ordinal, state, url = revisions.get(source_id, (None, None, None))
        sources.append(
            {
                "source_id": source_id,
                "source_key": source_key,
                "title": title,
                "current_revision": ordinal,
                "revision_state": state,
                "source_url": url,
                "cite_as": markdown_citation(title, url, ()),
            }
        )
    return {
        "state": "ok",
        "workspace_id": authorized.project_id,
        "sources": sources,
        "count": len(sources),
        "total": total,
        "offset": offset,
        "next_offset": offset + len(sources) if offset + len(sources) < total else None,
    }


def _identifier(value: object) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if text and len(text) <= _MAX_ID_CHARS else None


async def mcp_knowledge_feedback(
    db: AsyncSession, *, caller: Any, user: User, workspace_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    session_id = _identifier(arguments.get("session_id"))
    message_id = _identifier(arguments.get("message_id"))
    if session_id is None or message_id is None:
        return dict(NOT_FOUND)
    owner = (
        await db.execute(select(Session.project_id).where(Session.id == session_id, Session.user_id == user.id))
    ).scalar_one_or_none()
    if owner != workspace_id:
        # Another person's chat, another Workspace's chat and a missing chat are indistinguishable.
        return dict(NOT_FOUND)
    try:
        record = await submit_session_message_feedback(
            db,
            session_id=session_id,
            message_id=message_id,
            rating=arguments.get("rating"),
            liked=arguments.get("liked"),
            disliked=arguments.get("disliked"),
            aspects=arguments.get("aspects"),
            user_id=str(user.id),
        )
    except SessionFeedbackRefusedError as error:
        message = FEEDBACK_MESSAGES.get(error.reason, FEEDBACK_MESSAGES["invalid_request"])
        return refusal(error.state, error.reason, message)
    except NotFoundError:
        return dict(NOT_FOUND)
    except ConflictError:
        return dict(ASSISTANT_ONLY)
    return {
        "state": "recorded",
        "feedback_id": record.id,
        "message_id": record.message_id,
        "rating": record.rating,
        "aspects": dict(record.aspects),
    }


__all__ = ["mcp_knowledge_feedback", "mcp_knowledge_sources"]
