"""Coordinator telemetry roll-up helpers for sub-agent orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...models import SubAgentGroup
from ...time_utils import ensure_utc, utc_now_aware

_TERMINAL_CHILD_STATUSES = frozenset({"completed", "failed", "timed_out"})
_TERMINAL_GROUP_STATUSES = frozenset({"completed", "resumed", "timed_out"})


def _normalize_child_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _TERMINAL_CHILD_STATUSES:
        return normalized
    if normalized in {"error", "stopped"}:
        return "failed"
    return ""


def _isoformat(value: datetime | None) -> str | None:
    normalized = ensure_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat()


def _seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    normalized_start = ensure_utc(start)
    normalized_end = ensure_utc(end)
    if normalized_start is None or normalized_end is None:
        return None
    return max(int((normalized_end - normalized_start).total_seconds()), 0)


def _count_child_statuses(group: SubAgentGroup) -> dict[str, int]:
    counts = {"completed": 0, "failed": 0, "timed_out": 0}
    for value in dict(group.child_statuses_json or {}).values():
        normalized = _normalize_child_status(value)
        if normalized:
            counts[normalized] += 1
    return counts


def summarize_sub_agent_group_telemetry(
    group: SubAgentGroup,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a bounded coordinator roll-up from the current sub-agent group state."""

    reference_now = ensure_utc(now) or utc_now_aware()
    child_status_counts = _count_child_statuses(group)

    configured_child_count = len([item for item in list(group.child_session_ids_json or []) if str(item).strip()])
    total_children = max(int(group.total_count or 0), configured_child_count)
    completed_children = child_status_counts["completed"]
    failed_children = child_status_counts["failed"] + child_status_counts["timed_out"]
    terminal_children = completed_children + failed_children
    pending_children = max(total_children - terminal_children, 0)
    all_children_terminal = total_children == 0 or terminal_children >= total_children
    completion_ratio = round((terminal_children / total_children), 4) if total_children else 1.0

    status = str(group.status or "").strip().lower() or "unknown"
    group_is_terminal = status in _TERMINAL_GROUP_STATUSES
    counts_match_state = (
        int(group.completed_count or 0) == completed_children and int(group.failed_count or 0) == failed_children
    )

    terminal_state = status
    if not group_is_terminal and pending_children > 0:
        terminal_state = "in_progress"
    elif failed_children > 0 and status == "completed":
        terminal_state = "completed_with_failures"
    elif failed_children > 0 and status == "resumed":
        terminal_state = "resumed_with_failures"

    return {
        "coordinator_type": "sub_agent_group",
        "group_id": group.id,
        "parent_session_id": group.parent_session_id,
        "status": status,
        "terminal_state": terminal_state,
        "progress": {
            "total_children": total_children,
            "completed_children": completed_children,
            "failed_children": failed_children,
            "timed_out_children": child_status_counts["timed_out"],
            "terminal_children": terminal_children,
            "pending_children": pending_children,
            "completion_ratio": completion_ratio,
        },
        "readiness": {
            "all_children_terminal": all_children_terminal,
            "parent_resume_ready": all_children_terminal,
            "parent_resume_started": group.resumed_at is not None,
            "group_is_terminal": group_is_terminal,
            "counts_match_state": counts_match_state,
        },
        "timing": {
            "created_at": _isoformat(group.created_at),
            "updated_at": _isoformat(group.updated_at),
            "timeout_at": _isoformat(group.timeout_at),
            "completed_at": _isoformat(group.completed_at),
            "resumed_at": _isoformat(group.resumed_at),
            "elapsed_seconds": _seconds_between(group.created_at, group.completed_at or reference_now),
            "timeout_remaining_seconds": _seconds_between(reference_now, group.timeout_at),
        },
        "child_status_counts": child_status_counts,
        "last_error": str(group.last_error or "").strip() or None,
    }


__all__ = ["summarize_sub_agent_group_telemetry"]
