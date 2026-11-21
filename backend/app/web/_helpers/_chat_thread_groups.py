"""Helpers for nesting and grouping chat thread rows."""

from dataclasses import dataclass
from typing import Any

from ._serialization_ext import _thread_row_sort_key
from .serialization import _propagate_terminal_status_to_descendants, _sort_subthread_rows_recursively


@dataclass(slots=True)
class ChatThreadGroupingResult:
    active_chat_groups: list[dict[str, Any]]
    top_level_active_rows: list[dict[str, Any]]


def build_chat_thread_groups(
    *,
    active_session_rows: list[dict[str, Any]],
    archived_session_rows: list[dict[str, Any]],
) -> ChatThreadGroupingResult:
    active_session_rows_by_id = {row["id"]: row for row in active_session_rows}
    top_level_active_rows: list[dict[str, Any]] = []
    for row in active_session_rows:
        parent_session_id = str(row.get("parent_session_id") or "").strip()
        if parent_session_id and parent_session_id in active_session_rows_by_id:
            active_session_rows_by_id[parent_session_id]["sub_threads"].append(row)
            continue
        top_level_active_rows.append(row)

    for row in active_session_rows_by_id.values():
        row["sub_threads"] = _sort_subthread_rows_recursively(list(row.get("sub_threads") or []))
        row["sub_thread_count"] = len(row["sub_threads"])

    for row in top_level_active_rows:
        _propagate_terminal_status_to_descendants(row)

    grouped_active_sessions: dict[str, list[dict[str, Any]]] = {}
    for row in top_level_active_rows:
        project_id = str(row.get("project_id") or "").strip()
        project_name = str(row.get("project_name") or "").strip()
        group_key = project_id or ("" if project_name.lower() == "no project" else project_name)
        grouped_active_sessions.setdefault(group_key, []).append(row)
    active_chat_groups = [
        {
            "project_id": project_id,
            "project_name": rows[0].get("project_name") or "No project",
            "sessions": sorted(rows, key=_thread_row_sort_key, reverse=True),
        }
        for project_id, rows in grouped_active_sessions.items()
    ]

    thread_counter = 1
    for group in active_chat_groups:
        for row in group["sessions"]:
            row["thread_number"] = thread_counter
            thread_counter += 1
    for row in archived_session_rows:
        row["thread_number"] = thread_counter
        thread_counter += 1

    return ChatThreadGroupingResult(
        active_chat_groups=active_chat_groups,
        top_level_active_rows=top_level_active_rows,
    )
