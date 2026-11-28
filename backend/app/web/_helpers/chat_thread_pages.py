"""Thread list pagination helpers for the chat sidebar."""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Project, User
from ...models import Session as AgentSession
from ...models.session.session import CHAT_SIDEBAR_ORIGINS
from ._chat_thread_groups import build_chat_thread_groups
from ._serialization_ext import _serialize_thread_row
from .chat_thread_row_facts import session_last_activity_column
from .chat_thread_search import thread_search_clause
from .chat_thread_visibility import visible_thread_project_ids as _visible_thread_project_ids

CHAT_THREAD_GROUP_PAGE_SIZE = 20


def _sidebar_thread_filter() -> tuple[Any, ...]:
    # A chat with neither a title nor a user message (a failed first send) is not listed: it would only render as an
    # empty row.
    has_user_message = (
        select(Message.id).where(Message.session_id == AgentSession.id, Message.role == "user").exists()
    )
    return (
        AgentSession.origin.in_(CHAT_SIDEBAR_ORIGINS),
        or_(func.coalesce(AgentSession.metadata_["title"].as_string(), "") != "", has_user_message),
    )


def _active_top_level_filter(user: User) -> tuple[Any, ...]:
    return (
        AgentSession.user_id == user.id,
        AgentSession.parent_session_id.is_(None),
        or_(AgentSession.status.is_(None), AgentSession.status != "archived"),
        *_sidebar_thread_filter(),
    )


def _project_group_filter(project_id: str | None) -> Any:
    normalized = str(project_id or "").strip()
    if normalized:
        return AgentSession.project_id == normalized
    return AgentSession.project_id.is_(None)


def _project_visible_for_thread_sidebar(
    project_id: str | None,
    *,
    project_ids: set[str],
    include_no_project: bool,
) -> bool:
    normalized = str(project_id or "").strip()
    if normalized:
        return normalized in project_ids
    return include_no_project


async def list_visible_chat_projects(db: AsyncSession, *, user: User) -> list[Project]:
    project_ids, _admin = await _visible_thread_project_ids(db, user=user)
    if not project_ids:
        return []
    return (
        await db.execute(
            select(Project)
            .where(Project.id.in_(project_ids), Project.is_active.is_(True))
            .order_by(Project.name.asc())
        )
    ).scalars().all()


def _query_filter(query: str) -> tuple[Any, ...]:
    clause = thread_search_clause(query)
    return () if clause is None else (clause,)


async def count_chat_thread_groups(db: AsyncSession, *, user: User, query: str = "") -> dict[str, int]:
    project_ids, admin = await _visible_thread_project_ids(db, user=user)
    visibility_clauses = []
    if project_ids:
        visibility_clauses.append(AgentSession.project_id.in_(project_ids))
    if admin:
        visibility_clauses.append(AgentSession.project_id.is_(None))
    if not visibility_clauses:
        return {}

    rows = (
        await db.execute(
            select(AgentSession.project_id, func.count(AgentSession.id))
            .where(*_active_top_level_filter(user), or_(*visibility_clauses), *_query_filter(query))
            .group_by(AgentSession.project_id)
        )
    ).all()
    return {str(project_id or ""): int(count or 0) for project_id, count in rows}


async def load_chat_thread_group_page(
    db: AsyncSession,
    *,
    user: User,
    project_id: str | None,
    offset: int = 0,
    limit: int = CHAT_THREAD_GROUP_PAGE_SIZE,
    query: str = "",
) -> list[AgentSession]:
    normalized_limit = max(1, min(int(limit or CHAT_THREAD_GROUP_PAGE_SIZE), 100))
    normalized_offset = max(0, int(offset or 0))
    project_ids, admin = await _visible_thread_project_ids(db, user=user)
    if not _project_visible_for_thread_sidebar(
        project_id,
        project_ids=project_ids,
        include_no_project=admin,
    ):
        return []
    return (
        await db.execute(
            select(AgentSession)
            .where(*_active_top_level_filter(user), _project_group_filter(project_id), *_query_filter(query))
            .order_by(session_last_activity_column().desc(), AgentSession.id.desc())
            .offset(normalized_offset)
            .limit(normalized_limit)
        )
    ).scalars().all()


async def load_initial_chat_thread_pages(
    db: AsyncSession,
    *,
    user: User,
    group_counts_by_project_id: dict[str, int],
    page_size: int = CHAT_THREAD_GROUP_PAGE_SIZE,
) -> list[AgentSession]:
    sessions: list[AgentSession] = []
    for project_id in group_counts_by_project_id:
        sessions.extend(
            await load_chat_thread_group_page(
                db,
                user=user,
                project_id=project_id,
                offset=0,
                limit=page_size,
            )
        )
    return sessions


async def load_descendant_sessions(
    db: AsyncSession,
    *,
    user: User,
    top_level_session_ids: set[str],
) -> list[AgentSession]:
    descendant_sessions: list[AgentSession] = []
    pending_parent_ids = set(top_level_session_ids)
    seen_descendant_ids: set[str] = set()
    while pending_parent_ids:
        direct_children = (
            await db.execute(
                select(AgentSession)
                .where(
                    AgentSession.user_id == user.id,
                    AgentSession.parent_session_id.in_(pending_parent_ids),
                )
                .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
            )
        ).scalars().all()
        next_parent_ids: set[str] = set()
        for child in direct_children:
            if child.id in seen_descendant_ids:
                continue
            seen_descendant_ids.add(child.id)
            descendant_sessions.append(child)
            next_parent_ids.add(child.id)
        pending_parent_ids = next_parent_ids
    return descendant_sessions


def serialize_active_thread_groups(
    *,
    active_session_rows: list[dict[str, Any]],
    archived_session_rows: list[dict[str, Any]],
    group_counts_by_project_id: dict[str, int],
    page_size: int = CHAT_THREAD_GROUP_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    thread_groups = build_chat_thread_groups(
        active_session_rows=active_session_rows,
        archived_session_rows=archived_session_rows,
    )
    groups_by_project_id = {str(group.get("project_id") or ""): group for group in thread_groups.active_chat_groups}
    serialized_groups: list[dict[str, Any]] = []
    ordered_counts = sorted(
        group_counts_by_project_id.items(),
        key=lambda item: (
            0 if not item[0] else 1,
            str((groups_by_project_id.get(item[0]) or {}).get("project_name") or item[0]).lower(),
        ),
    )
    for project_id, total_count in ordered_counts:
        group = groups_by_project_id.get(project_id)
        project_name = group["project_name"] if group else "No project"
        sessions = group["sessions"] if group else []
        loaded_count = min(len(sessions), total_count)
        serialized_groups.append(
            {
                "projectId": project_id,
                "projectName": project_name,
                "sessions": [_serialize_thread_row(row) for row in sessions],
                "totalThreadCount": total_count,
                "loadedThreadCount": loaded_count,
                "nextOffset": min(page_size, total_count),
                "hasMore": total_count > page_size,
                "pageSize": page_size,
            }
        )
    return serialized_groups, thread_groups.top_level_active_rows


def serialize_thread_group_page(
    *,
    project_id: str,
    project_name: str,
    active_session_rows: list[dict[str, Any]],
    total_count: int,
    offset: int,
    page_size: int,
) -> dict[str, Any]:
    thread_groups = build_chat_thread_groups(active_session_rows=active_session_rows, archived_session_rows=[])
    group = thread_groups.active_chat_groups[0] if thread_groups.active_chat_groups else {
        "project_id": project_id,
        "project_name": project_name,
        "sessions": [],
    }
    next_offset = min(max(0, int(offset or 0)) + max(0, len(group["sessions"])), total_count)
    return {
        "projectId": project_id,
        "projectName": group.get("project_name") or project_name,
        "sessions": [_serialize_thread_row(row) for row in group["sessions"]],
        "totalThreadCount": total_count,
        "loadedThreadCount": next_offset,
        "nextOffset": next_offset,
        "hasMore": next_offset < total_count,
        "pageSize": page_size,
    }
