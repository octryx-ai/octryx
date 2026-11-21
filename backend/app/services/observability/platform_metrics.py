"""Platform operation counters for Prometheus (``octryx_*``), counted where the facts are written.

Metrics never go through the database. The ORM hook of :mod:`agent_metrics` hands every committed insert or update here:

- a task run counts when it is queued, starts and finishes (the database-backed queue's depth is their difference,
  an approximation; the Redis queue's depth is read from Redis, see ``metrics_render``);
- a code graph index run that reaches a final status counts by status and backend, with its duration and files;
- an SLA breach counts by type and severity;
- an outbound webhook delivery counts every status it reaches;
- a secret rotation log row counts by action;

Counters start at zero with the process; ``rate()`` and ``increase()`` handle that. Grafana sums over processes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import inspect

from .metric_types import Counter, Histogram, _Metric

CODE_GRAPH_SECONDS = (1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)
CODE_GRAPH_OPEN = frozenset({"pending", "queued", "running", "indexing"})

CODE_GRAPH_RUNS = Counter("octryx_code_graph_index_runs_total", "Native code graph index runs finished, by"
                          " status and backend", ("status", "backend"))
CODE_GRAPH_DURATION = Histogram("octryx_code_graph_index_duration_seconds", "Native code graph index run"
                                " duration in seconds, by status", ("status",), CODE_GRAPH_SECONDS)
CODE_GRAPH_FILES = Counter("octryx_code_graph_files_indexed_count_total", "Files recorded by finished native"
                           " code graph index runs", ())
SLA_BREACHES = Counter("octryx_sla_breaches_recorded_total", "SLA breaches recorded, by type and severity",
                       ("breach_type", "severity"))
WEBHOOK_DELIVERIES = Counter("octryx_outbound_webhook_delivery_status_total", "Outbound webhook deliveries"
                             " reaching a status (pending, delivered, failed, ...)", ("status",))
SECRET_ROTATIONS = Counter("octryx_secret_rotation_logged_total", "Secret rotation and expiry log rows, by"
                           " action", ("action",))

TASK_RUNS_ENQUEUED = Counter("octryx_task_runs_enqueued_total", "Task runs queued, by trigger type", ("kind",))
TASK_RUNS_STARTED = Counter("octryx_task_runs_started_total", "Task runs started, by trigger type", ("kind",))
TASK_RUNS_FINISHED = Counter("octryx_task_runs_finished_total", "Task runs finished, by trigger type and status",
                             ("kind", "status"))
TASK_RUN_WAITING = frozenset({"queued", "pending"})
TASK_RUN_RUNNING = "running"

METRICS: tuple[_Metric, ...] = (TASK_RUNS_ENQUEUED, TASK_RUNS_STARTED, TASK_RUNS_FINISHED, CODE_GRAPH_RUNS,
                                CODE_GRAPH_DURATION, CODE_GRAPH_FILES, SLA_BREACHES,
                                WEBHOOK_DELIVERIES, SECRET_ROTATIONS)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()


def _status_reached(row: Any, new: bool) -> str | None:
    """The status the write set: on insert the row's status, on update a changed one."""
    if new:
        return inspect(row).dict.get("status")
    history = inspect(row).attrs["status"].history
    return history.added[0] if history.added and history.deleted != history.added else None


def written(row: Any, table: str, new: bool) -> Callable[[], None] | None:
    if table == "task_runs":
        status = _status_reached(row, new)
        if not status:
            return None
        kind = inspect(row).dict.get("trigger_type") or "unknown"
        if status in TASK_RUN_WAITING:
            return lambda: TASK_RUNS_ENQUEUED.inc(kind=kind)
        if status == TASK_RUN_RUNNING:
            return lambda: TASK_RUNS_STARTED.inc(kind=kind)
        return lambda: TASK_RUNS_FINISHED.inc(kind=kind, status=status)
    if table == "code_graph_runs":
        status = _status_reached(row, new)
        if not status or status in CODE_GRAPH_OPEN:
            return None
        state = inspect(row).dict
        backend, duration, files = state.get("backend") or "unknown", state.get("duration_ms"), state.get("file_count")

        def count() -> None:
            CODE_GRAPH_RUNS.inc(status=status, backend=backend)
            if duration is not None:
                CODE_GRAPH_DURATION.observe(duration / 1000, status=status)
            if files:
                CODE_GRAPH_FILES.inc(int(files))

        return count
    if table == "sla_breaches" and new:
        breach_type, severity = row.breach_type or "unknown", row.severity or "unknown"
        return lambda: SLA_BREACHES.inc(breach_type=breach_type, severity=severity)
    if table == "outbound_webhook_deliveries":
        status = _status_reached(row, new)
        return (lambda: WEBHOOK_DELIVERIES.inc(status=status)) if status else None
    if table == "secret_rotation_log" and new:
        action = row.action or "unknown"
        return lambda: SECRET_ROTATIONS.inc(action=action)
    return None
