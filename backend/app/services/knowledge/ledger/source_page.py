"""Keyset-paged, optionally title-filtered source list of one Workspace.

The Documents page must reach every source the reader may see, not only the
newest ``MAX_SOURCE_LIMIT`` (judge finding J-C-001). Pages are newest-first by
``(created_at, id)`` and the continuation is an opaque cursor; the same
Workspace authorization and per-source ACL as :func:`queries.list_sources` apply,
so a cursor never widens what a reader can list.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource, KnowledgeSourceRevision
from ..access.authorization import AuthorizedWorkspace
from ..access.source_acl import visible_source
from .errors import EvidenceLedgerContractError, InvalidEvidenceRequestError
from .queries import DEFAULT_SOURCE_LIMIT, MAX_SOURCE_LIMIT, SourceSummary, _validated_limit

MAX_QUERY_LENGTH = 200
_CURSOR_SEPARATOR = "|"


def encode_source_cursor(created_at: datetime, source_id: str) -> str:
    raw = f"{created_at.isoformat()}{_CURSOR_SEPARATOR}{source_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_source_cursor(cursor: object) -> tuple[datetime, str]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 256:
        raise InvalidEvidenceRequestError()
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, source_id = raw.split(_CURSOR_SEPARATOR, 1)
        return datetime.fromisoformat(stamp), source_id
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidEvidenceRequestError() from None


def _title_filter(query: object):
    if query is None:
        return None
    if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH:
        raise InvalidEvidenceRequestError()
    text = query.strip()
    if not text:
        return None
    # Literal substring match: LIKE wildcards in the input are escaped.
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        func.lower(KnowledgeEvidenceSource.display_title).like(pattern, escape="\\"),
        func.lower(KnowledgeEvidenceSource.source_key).like(pattern, escape="\\"),
    )


def _page_conditions(authorized: AuthorizedWorkspace, cursor: object, query: object) -> list:
    """Workspace, ACL, optional title filter and keyset position of one page."""
    conditions = [
        KnowledgeEvidenceSource.project_id == authorized.project_id,
        visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
    ]
    title = _title_filter(query)
    if title is not None:
        conditions.append(title)
    if cursor is not None:
        created_at, source_id = decode_source_cursor(cursor)
        conditions.append(
            or_(
                KnowledgeEvidenceSource.created_at < created_at,
                and_(KnowledgeEvidenceSource.created_at == created_at, KnowledgeEvidenceSource.id < source_id),
            )
        )
    return conditions


def _page_statement(authorized: AuthorizedWorkspace, conditions: list, bounded: int):
    # One row more than the page: its presence is what says another page follows.
    return (
        select(
            KnowledgeEvidenceSource.id,
            KnowledgeEvidenceSource.source_key,
            KnowledgeEvidenceSource.display_title,
            func.count(KnowledgeSourceRevision.id),
            func.max(KnowledgeSourceRevision.revision_ordinal),
            KnowledgeEvidenceSource.created_at,
        )
        .outerjoin(
            KnowledgeSourceRevision,
            (KnowledgeSourceRevision.source_id == KnowledgeEvidenceSource.id)
            & (KnowledgeSourceRevision.project_id == authorized.project_id),
        )
        .where(*conditions)
        .group_by(
            KnowledgeEvidenceSource.id,
            KnowledgeEvidenceSource.source_key,
            KnowledgeEvidenceSource.display_title,
            KnowledgeEvidenceSource.created_at,
        )
        .order_by(KnowledgeEvidenceSource.created_at.desc(), KnowledgeEvidenceSource.id.desc())
        .limit(bounded + 1)
    )


async def list_source_page(
    db: AsyncSession,
    authorized: AuthorizedWorkspace,
    *,
    limit: object = None,
    cursor: object = None,
    query: object = None,
) -> tuple[tuple[SourceSummary, ...], str | None]:
    """One newest-first page of visible sources and the cursor of the next page."""
    if type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    bounded = _validated_limit(limit, DEFAULT_SOURCE_LIMIT, MAX_SOURCE_LIMIT)
    conditions = _page_conditions(authorized, cursor, query)
    statement = _page_statement(authorized, conditions, bounded)
    rows = (await db.execute(statement)).all()
    page = rows[:bounded]
    next_cursor = encode_source_cursor(page[-1][5], page[-1][0]) if len(rows) > bounded and page else None
    return (
        tuple(
            SourceSummary(
                source_id=row[0],
                source_key=row[1],
                display_title=row[2],
                revision_count=int(row[3] or 0),
                latest_revision_ordinal=int(row[4]) if row[4] is not None else None,
            )
            for row in page
        ),
        next_cursor,
    )
