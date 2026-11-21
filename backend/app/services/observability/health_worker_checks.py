"""The background workers' part of the platform health checks: a worker's task, the scheduler and its task queue
dispatcher (read from the objects in this process, no I/O).
"""

from __future__ import annotations

import time
from typing import Any

STATUS_UNKNOWN = "unknown"
STATUS_DISABLED = "disabled"


def _task_component_check(
    *,
    worker: Any,
    stopped_message: str,
    task_attr: str = "_task",
    allow_missing_task: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    task = getattr(worker, task_attr, None)
    running = bool(task is not None and not task.done())
    if task is None and allow_missing_task:
        # A worker that never started is not "ok": its state is unknown.
        return {"status": STATUS_UNKNOWN, "response_time_ms": int((time.perf_counter() - started) * 1000),
                "error": "not started"}
    return {
        "status": "ok" if running else "error",
        "response_time_ms": int((time.perf_counter() - started) * 1000),
        "error": None if running else stopped_message,
    }


# What a stopped background worker reports, by component.
STOPPED_MESSAGES = {
    "channel_router": "Channel router stopped unexpectedly",
    "retention_worker": "Retention worker stopped unexpectedly",
    "outbound_webhook_worker": "Outbound webhook worker stopped unexpectedly",
    "analytics_worker": "Analytics worker stopped unexpectedly",
    "prefetch_worker": "Prefetch worker stopped unexpectedly",
    "worker_monitor_worker": "Worker monitor worker stopped unexpectedly",
    "worker_agenda_worker": "Worker agenda worker stopped unexpectedly",
    "worker_report_worker": "Worker report worker stopped unexpectedly",
    "worker_pool_worker": "Worker pool worker stopped unexpectedly",
    "sla_monitor_worker": "SLA monitor worker stopped unexpectedly",
    "secret_expiry_worker": "Secret expiry worker stopped unexpectedly",
    "session_workspace_cleanup_worker": "Session workspace cleanup worker stopped unexpectedly",
}
# Every component that runs only with background workers, in the order of the checks.
WORKER_COMPONENTS = (
    "scheduler",
    "task_queue_dispatcher",
    "channel_router",
    "retention_worker",
    "outbound_webhook_worker",
    "connector_health_worker",
    "analytics_worker",
    "prefetch_worker",
    "worker_monitor_worker",
    "worker_agenda_worker",
    "worker_report_worker",
    "worker_pool_worker",
    "sla_monitor_worker",
    "secret_expiry_worker",
    "session_workspace_cleanup_worker",
)


def scheduler_checks(task_scheduler: Any) -> dict[str, dict[str, Any]]:
    """The scheduler and its task queue dispatcher."""
    checks: dict[str, dict[str, Any]] = {}
    scheduler_started = time.perf_counter()
    scheduler_obj = getattr(task_scheduler, "scheduler", None)
    scheduler_running = bool(getattr(scheduler_obj, "running", False))
    checks["scheduler"] = {
        "status": "ok" if scheduler_running or scheduler_obj is not None else "error",
        "response_time_ms": int((time.perf_counter() - scheduler_started) * 1000),
        "error": None if scheduler_running or scheduler_obj is not None else "Scheduler is not initialized",
    }

    dispatch_started = time.perf_counter()
    dispatch_task = getattr(task_scheduler, "_queue_dispatch_task", None)
    dispatch_running = bool(dispatch_task is not None and not dispatch_task.done())
    checks["task_queue_dispatcher"] = {
        "status": "ok" if dispatch_running else "error",
        "response_time_ms": int((time.perf_counter() - dispatch_started) * 1000),
        "error": None if dispatch_running else "Task queue dispatcher is not running",
    }
    return checks


def task_checks(workers: tuple[tuple[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {
        component: _task_component_check(worker=worker, stopped_message=STOPPED_MESSAGES[component])
        for component, worker in workers
    }
