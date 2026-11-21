"""Chat sidebar list: group pages and server-side search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.web._helpers._serialization_ext import _serialize_thread_row
from app.web._helpers.api_guards import _require_api_user

from ...db import get_db
from .._helpers.chat_thread_group_page import build_thread_group_page, build_thread_search_groups
from .._helpers.chat_thread_pages import CHAT_THREAD_GROUP_PAGE_SIZE
from .._helpers.chat_thread_rows import build_chat_thread_rows
from .._helpers.chat_thread_scope import count_archived_threads, load_archived_threads

router = APIRouter()


@router.get("/chat/api/thread-groups")
async def chat_thread_group_page_api(
    request: Request,
    project_id: str = "",
    offset: int = 0,
    limit: int = CHAT_THREAD_GROUP_PAGE_SIZE,
    q: str = "",
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    page = await build_thread_group_page(
        db, user=user, project_id=project_id, offset=offset, limit=limit, query=q[:200]
    )
    return JSONResponse(page)


@router.get("/chat/api/thread-groups/search")
async def chat_thread_search_api(
    request: Request,
    q: str = "",
    limit: int = CHAT_THREAD_GROUP_PAGE_SIZE,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_api_user(request, db)
    query = q.strip()[:200]
    if not query:
        return JSONResponse({"query": "", "groups": []})
    groups = await build_thread_search_groups(db, user=user, query=query, limit=limit)
    return JSONResponse({"query": query, "groups": groups})


@router.get("/chat/api/threads/archived")
async def chat_archived_threads_api(
    request: Request,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Archived chats, newest activity first, for the sidebar's archived view (Restore)."""
    user = await _require_api_user(request, db)
    total = await count_archived_threads(db, user=user)
    sessions = await load_archived_threads(db, user=user, offset=offset, limit=limit)
    rows = await build_chat_thread_rows(db, sessions=sessions, selected_session=None, automatic_runtime_label="")
    next_offset = max(0, offset) + len(sessions)
    return JSONResponse(
        {
            "total": total,
            "threads": [_serialize_thread_row(row) for row in rows.rows],
            "nextOffset": next_offset,
            "hasMore": next_offset < total,
        }
    )
