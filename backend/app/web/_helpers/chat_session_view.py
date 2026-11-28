"""The selected-session view: what the chat needs to switch to one thread, without the workspace bootstrap. Its keys
come from the bootstrap's own builder, so both payloads agree field by field."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import User
from ._chat_runtime_selection import AUTOMATIC_RUNTIME_LABEL, resolve_chat_runtime_selection
from ._chat_selected_view_fields import build_selected_view_fields
from ._chat_thread_groups import build_chat_thread_groups
from .chat_thread_pages import load_descendant_sessions
from .chat_thread_row_facts import session_last_activity
from .chat_thread_rows import build_chat_thread_rows
from .serialization import _resolve_root_session, _sort_datetime_value

__all__ = ["build_chat_session_view"]


async def _load_selected_thread_tree(db: AsyncSession, *, user: User, selected_session: AgentSession) -> list[AgentSession]:
    # Owner-scoped.
    root = await _resolve_root_session(db, selected_session)
    root_id = root.id if root is not None else selected_session.id
    descendants = await load_descendant_sessions(db, user=user, top_level_session_ids={root_id})
    sessions_by_id = {session.id: session for session in [selected_session, *descendants]}
    if root is not None and root.user_id == user.id:
        sessions_by_id[root.id] = root
    return sorted(
        sessions_by_id.values(),
        key=lambda session: _sort_datetime_value(session_last_activity(session)),
        reverse=True,
    )


async def build_chat_session_view(
    db: AsyncSession,
    *,
    user: User,
    session_id: str,
    chat_message_page_size: int | None = None,
) -> dict[str, Any]:
    # A missing or foreign id is reported, not swapped.
    if chat_message_page_size is None:
        from .chat_state import CHAT_MESSAGE_PAGE_SIZE

        chat_message_page_size = CHAT_MESSAGE_PAGE_SIZE
    selected_session = (
        await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
    ).scalar_one_or_none()
    task_run_map: dict[str, Any] = {}
    latest_task_run_by_session_id: dict[str, Any] = {}
    top_level_active_rows: list[dict[str, Any]] = []
    selected_row = None
    if selected_session is not None:
        row_payload = await build_chat_thread_rows(
            db,
            sessions=await _load_selected_thread_tree(db, user=user, selected_session=selected_session),
            selected_session=selected_session,
            automatic_runtime_label=AUTOMATIC_RUNTIME_LABEL,
        )
        task_run_map = row_payload.task_run_map
        latest_task_run_by_session_id = row_payload.latest_task_run_by_session_id
        active_rows: list[dict[str, Any]] = []
        archived_rows: list[dict[str, Any]] = []
        for row in row_payload.rows:
            is_archived = str(row.get("status") or "").strip().lower() == "archived"
            (archived_rows if is_archived else active_rows).append(row)
        top_level_active_rows = build_chat_thread_groups(
            active_session_rows=active_rows,
            archived_session_rows=archived_rows,
        ).top_level_active_rows
        selected_row = row_payload.selected_row
        if selected_row is not None:
            # A tree-local ordinal would be wrong; see the module docstring.
            selected_row = {**selected_row, "thread_number": 0}
    selection = await resolve_chat_runtime_selection(db, user=user, selected_session=selected_session)
    return await build_selected_view_fields(
        db,
        user=user,
        selected_session=selected_session,
        selected_row=selected_row,
        selection=selection,
        requested_session_missing=selected_session is None,
        task_run_map=task_run_map,
        latest_task_run_by_session_id=latest_task_run_by_session_id,
        top_level_active_rows=top_level_active_rows,
        requested_agent_id="",
        chat_message_page_size=chat_message_page_size,
    )
