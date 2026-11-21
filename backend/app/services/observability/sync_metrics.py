"""Work item syncs in Prometheus, from memory (incremental syncs run every minute; metrics never read
the database): runs by kind (jira, servicenow, ...), window (full, incremental) and outcome (completed, blocked,
failed, skipped), the items each run fetched, and its duration. Counted where the run ends, in the process that ran
it (API for a person's start, worker for a schedule)."""

from __future__ import annotations

from .metric_types import Counter, Histogram

SYNC_RUNS = Counter("octryx_sync_runs_total", "Work item sync runs by kind, window and outcome (skipped: another run"
                    " of the configuration was going)", ("kind", "window", "outcome"))
SYNC_ITEMS = Counter("octryx_sync_items_total", "Items a work item sync run fetched from its source",
                     ("kind", "window"))
SYNC_SECONDS = Histogram("octryx_sync_duration_seconds", "Work item sync run duration in seconds",
                         ("kind", "window"), (0.5, 1, 2, 5, 10, 30, 60, 120, 300, 900))
METRICS = (SYNC_RUNS, SYNC_ITEMS, SYNC_SECONDS)


def record_run(*, kind: str, window: str, outcome: str, items: int = 0, seconds: float | None = None) -> None:
    SYNC_RUNS.inc(kind=kind, window=window or "none", outcome=outcome)
    SYNC_ITEMS.inc(items, kind=kind, window=window or "none")
    if seconds is not None:
        SYNC_SECONDS.observe(seconds, kind=kind, window=window or "none")


def render() -> list[str]:
    return [line for metric in METRICS for line in metric.render()]


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()


__all__ = ["SYNC_ITEMS", "SYNC_RUNS", "SYNC_SECONDS", "record_run", "render", "reset"]
