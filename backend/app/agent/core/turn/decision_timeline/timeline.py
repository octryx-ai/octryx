"""The decision timeline of a turn trace: one bounded list of operator-readable events."""

from __future__ import annotations

from typing import Any

MAX_TIMELINE_EVENTS = 32
MAX_VISIBLE_ITEMS = 40


def compact_items(items: list[str], *, limit: int = MAX_VISIBLE_ITEMS) -> tuple[list[str], int]:
    clean_items = [str(item or "").strip() for item in items if str(item or "").strip()]
    clean_items = sorted(dict.fromkeys(clean_items))
    return clean_items[:limit], max(0, len(clean_items) - limit)


def _metadata_without_empty_values(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if value not in (None, "", [], {}, ())
    }


def append_decision_timeline_event(
    context_snapshot: dict[str, Any],
    *,
    phase: str,
    title: str,
    status: str = "info",
    detail: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one operator-readable decision event to a turn context snapshot."""

    if not isinstance(context_snapshot, dict):
        return {}
    timeline = context_snapshot.get("decision_timeline")
    if not isinstance(timeline, list):
        timeline = []
    next_index = len(timeline) + 1
    event = {
        "index": next_index,
        "phase": str(phase or "decision").strip() or "decision",
        "title": str(title or "Decision").strip() or "Decision",
        "status": str(status or "info").strip().lower() or "info",
    }
    if detail:
        event["detail"] = str(detail).strip()
    clean_metadata = _metadata_without_empty_values(metadata)
    if clean_metadata:
        event["metadata"] = clean_metadata
    timeline.append(event)
    context_snapshot["decision_timeline"] = timeline[-MAX_TIMELINE_EVENTS:]
    return event
