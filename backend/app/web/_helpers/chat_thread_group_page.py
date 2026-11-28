"""One page of a chat sidebar group, and the search groups."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runtime_options import list_chat_runtime_options

from ...models import User
from .chat_thread_pages import (
    CHAT_THREAD_GROUP_PAGE_SIZE,
    count_chat_thread_groups,
    load_chat_thread_group_page,
    load_descendant_sessions,
    serialize_thread_group_page,
)
from .chat_thread_rows import build_chat_thread_rows


def _normalized_limit(limit: int) -> int:
    return max(1, min(int(limit or CHAT_THREAD_GROUP_PAGE_SIZE), 100))


async def build_thread_group_page(
    db: AsyncSession,
    *,
    user: User,
    project_id: str,
    offset: int = 0,
    limit: int = CHAT_THREAD_GROUP_PAGE_SIZE,
    query: str = "",
    group_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    normalized_offset = max(0, int(offset or 0))
    normalized_limit = _normalized_limit(limit)
    counts = group_counts if group_counts is not None else await count_chat_thread_groups(db, user=user, query=query)
    if normalized_project_id not in counts:
        return serialize_thread_group_page(
            project_id=normalized_project_id,
            project_name="No project" if not normalized_project_id else "",
            active_session_rows=[],
            total_count=0,
            offset=normalized_offset,
            page_size=normalized_limit,
        )
    top_level_sessions = await load_chat_thread_group_page(
        db,
        user=user,
        project_id=normalized_project_id,
        offset=normalized_offset,
        limit=normalized_limit,
        query=query,
    )
    descendant_sessions = await load_descendant_sessions(
        db, user=user, top_level_session_ids={session.id for session in top_level_sessions}
    )
    runtime_options = await list_chat_runtime_options(db)
    runtime_label_by_id = {option["value"]: option["label"] for option in runtime_options}
    row_payload = await build_chat_thread_rows(
        db,
        sessions=[*top_level_sessions, *descendant_sessions],
        selected_session=None,
        automatic_runtime_label=runtime_label_by_id.get("", "Automatic fallback chain"),
    )
    active_rows = [row for row in row_payload.rows if str(row.get("status") or "").strip().lower() != "archived"]
    project_name = active_rows[0].get("project_name") if active_rows else (
        "No project" if not normalized_project_id else ""
    )
    return serialize_thread_group_page(
        project_id=normalized_project_id,
        project_name=str(project_name or ""),
        active_session_rows=active_rows,
        total_count=int(counts.get(normalized_project_id, 0)),
        offset=normalized_offset,
        page_size=normalized_limit,
    )


async def build_thread_search_groups(
    db: AsyncSession,
    *,
    user: User,
    query: str,
    limit: int = CHAT_THREAD_GROUP_PAGE_SIZE,
) -> list[dict[str, Any]]:
    counts = await count_chat_thread_groups(db, user=user, query=query)
    groups = [
        await build_thread_group_page(
            db, user=user, project_id=project_id, limit=limit, query=query, group_counts=counts
        )
        for project_id, count in counts.items()
        if count > 0
    ]
    return sorted(groups, key=lambda group: (group["projectId"] != "", str(group["projectName"]).lower()))


__all__ = ["build_thread_group_page", "build_thread_search_groups"]
