"""In-memory database concurrency counters for runtime observability."""

from __future__ import annotations

from collections import Counter

_DB_CONCURRENCY_COUNTER: Counter[tuple[str, str]] = Counter()


def record_db_concurrency_event(component: str, event: str) -> None:
    normalized_component = str(component or "unknown").strip().lower().replace(" ", "_") or "unknown"
    normalized_event = str(event or "unknown").strip().lower().replace(" ", "_") or "unknown"
    _DB_CONCURRENCY_COUNTER[(normalized_component, normalized_event)] += 1


def reset_db_concurrency_events() -> None:
    _DB_CONCURRENCY_COUNTER.clear()
