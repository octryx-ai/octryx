"""Shared helper utilities for worker pool services."""

from decimal import Decimal

from ...models import Task, TaskQueueEntry, TaskRun, WorkerRateLimit

PRIORITY_LABELS = {
    10: "P0",
    9: "P1",
    8: "P1",
    7: "P2",
    6: "P2",
    5: "P2",
    4: "P3",
    3: "P3",
    2: "P4",
    1: "P4",
}


def _priority_label(priority: int) -> str:
    return PRIORITY_LABELS[max(1, min(int(priority or 5), 10))]


def explicit_required_domain(task: Task | None, queue_entry: TaskQueueEntry | None = None) -> str | None:
    if queue_entry and str(queue_entry.required_domain or "").strip():
        return str(queue_entry.required_domain).strip().lower()
    config = dict((task.config or {}) if task else {})
    explicit = str(config.get("required_domain") or config.get("domain") or "").strip().lower()
    if explicit:
        return explicit
    return None


def infer_required_domain(task: Task | None, queue_entry: TaskQueueEntry | None = None) -> str:
    return explicit_required_domain(task, queue_entry) or "any"


def _should_pause_low_priority(rate_limit: WorkerRateLimit, priority: int) -> bool:
    hourly_cost = Decimal(str(rate_limit.current_hour_cost or 0))
    daily_cost = Decimal(str(rate_limit.current_day_cost or 0))
    if (
        rate_limit.on_cost_limit == "pause_low_priority"
        and (
            hourly_cost >= Decimal(str(rate_limit.max_cost_per_hour))
            or daily_cost >= Decimal(str(rate_limit.max_cost_per_day))
        )
        and int(priority or 5) <= 4
    ):
        return True
    if rate_limit.on_minute_limit == "queue" and float(rate_limit.current_rpm or 0) >= float(
        rate_limit.max_requests_per_minute or 60
    ):
        return True
    if (
        int(rate_limit.current_hour_tokens or 0) >= int(rate_limit.max_tokens_per_hour or 500000)
        and int(priority or 5) <= 4
    ):
        return True
    return False


def _run_duration_minutes(task_run: TaskRun) -> float | None:
    if not task_run.started_at or not task_run.completed_at:
        return None
    return max(0.1, round((task_run.completed_at - task_run.started_at).total_seconds() / 60.0, 2))


def _derive_expertise_level(tasks_completed: int, success_rate: float) -> str:
    if tasks_completed >= 20 and success_rate >= 0.85:
        return "expert"
    if tasks_completed >= 5 and success_rate >= 0.65:
        return "intermediate"
    return "beginner"
