"""Server-side thread selection for the chat sidebar: search clause, scope resolution, counts.

A *scope* is "all chats of this Workspace that match ``query`` and started at or before ``as_of``,
except ``except_ids``" — the client never has to hold the ids of unloaded rows. Every resolution
goes through the same ownership/visibility filter as the sidebar list, so a scope or an id can never
reach another user's threads or a Workspace the user cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import User
from .chat_thread_pages import _active_top_level_filter, _project_group_filter, _sidebar_thread_filter
from .chat_thread_row_facts import session_last_activity_column
from .chat_thread_search import thread_search_clause
from .chat_thread_visibility import visible_thread_project_ids as _visible_thread_project_ids

MAX_BULK_IDS = 5000


@dataclass(slots=True)
class ThreadScope:
    project_id: str = ""
    query: str = ""
    as_of: datetime | None = None
    except_ids: list[str] = field(default_factory=list)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


async def _visibility_clause(db: AsyncSession, *, user: User) -> Any | None:
    project_ids, admin = await _visible_thread_project_ids(db, user=user)
    clauses: list[Any] = []
    if project_ids:
        clauses.append(AgentSession.project_id.in_(project_ids))
    if admin:
        clauses.append(AgentSession.project_id.is_(None))
    return or_(*clauses) if clauses else None


def _archived_top_level_filter(user: User) -> tuple[Any, ...]:
    """Restore works on the archived top-level threads of the user (the undo of an archive)."""
    return (
        AgentSession.user_id == user.id,
        AgentSession.parent_session_id.is_(None),
        AgentSession.status == "archived",
        *_sidebar_thread_filter(),
    )


def _scope_clause(scope: ThreadScope) -> Any:
    clauses = [_project_group_filter(scope.project_id)]
    search = thread_search_clause(scope.query)
    if search is not None:
        clauses.append(search)
    as_of = _naive_utc(scope.as_of)
    if as_of is not None:
        clauses.append(AgentSession.started_at <= as_of)
    except_ids = [str(item) for item in scope.except_ids if str(item or "").strip()]
    if except_ids:
        clauses.append(AgentSession.id.not_in(except_ids))
    return and_(*clauses)


async def resolve_thread_targets(
    db: AsyncSession,
    *,
    user: User,
    ids: list[str],
    scopes: list[ThreadScope],
    archived: bool = False,
) -> tuple[list[AgentSession], list[str]]:
    """The owned, visible top-level threads named by ``ids`` or ``scopes``, plus the ids not found."""
    visibility = await _visibility_clause(db, user=user)
    requested_ids = list(dict.fromkeys(str(item) for item in ids if str(item or "").strip()))
    if visibility is None:
        return [], requested_ids
    base = _archived_top_level_filter(user) if archived else _active_top_level_filter(user)
    selectors: list[Any] = []
    if requested_ids:
        selectors.append(AgentSession.id.in_(requested_ids))
    if not archived:
        selectors.extend(_scope_clause(scope) for scope in scopes)
    if not selectors:
        return [], []
    sessions = (
        await db.execute(
            select(AgentSession)
            .where(*base, visibility, or_(*selectors))
            .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
            .limit(MAX_BULK_IDS)
        )
    ).scalars().all()
    found = {session.id for session in sessions}
    return list(sessions), [item for item in requested_ids if item not in found]


async def count_thread_scope(db: AsyncSession, *, user: User, scope: ThreadScope) -> int:
    """How many threads a scope covers right now (the banner numbers of the sidebar)."""
    visibility = await _visibility_clause(db, user=user)
    if visibility is None:
        return 0
    return int(
        (
            await db.execute(
                select(func.count(AgentSession.id)).where(
                    *_active_top_level_filter(user), visibility, _scope_clause(scope)
                )
            )
        ).scalar_one()
        or 0
    )


async def count_archived_threads(db: AsyncSession, *, user: User) -> int:
    """Archived chats the user can restore from the sidebar ("Archived chats · N")."""
    visibility = await _visibility_clause(db, user=user)
    if visibility is None:
        return 0
    return int(
        (
            await db.execute(
                select(func.count(AgentSession.id)).where(*_archived_top_level_filter(user), visibility)
            )
        ).scalar_one()
        or 0
    )


async def load_archived_threads(db: AsyncSession, *, user: User, offset: int, limit: int) -> list[AgentSession]:
    visibility = await _visibility_clause(db, user=user)
    if visibility is None:
        return []
    return list(
        (
            await db.execute(
                select(AgentSession)
                .where(*_archived_top_level_filter(user), visibility)
                .order_by(session_last_activity_column().desc(), AgentSession.id.desc())
                .offset(max(0, offset))
                .limit(max(1, min(limit, 100)))
            )
        ).scalars().all()
    )


__all__ = [
    "MAX_BULK_IDS",
    "count_archived_threads",
    "load_archived_threads",
    "ThreadScope",
    "count_thread_scope",
    "resolve_thread_targets",
]
