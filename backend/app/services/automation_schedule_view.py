"""Schedulers and Actions in words: common cron shapes as sentences, and the next fire time. Day-of-week numbers follow
APScheduler (Monday = 0)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Scheduler, Task, TaskRun
from ..models.integration.webhook import Webhook

WORK_INTAKE_TASK_PREFIX = "secure_work_"
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_ALIASES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def is_work_intake_task(task: Any) -> bool:
    return str(getattr(task, "task_type", "") or "").startswith(WORK_INTAKE_TASK_PREFIX)


def _day(value: str) -> int | None:
    value = value.strip().lower()
    if value in _DAY_ALIASES:
        return _DAY_ALIASES[value]
    return int(value) if value.isdigit() and int(value) < 7 else None


def _days(field: str) -> str | None:
    if field == "*":
        return "Every day"
    if "-" in field and "," not in field:
        start, end = (_day(part) for part in field.split("-", 1))
        if (start, end) == (0, 4):
            return "Weekdays"
        if start is not None and end is not None:
            return f"{_DAY_NAMES[start]} to {_DAY_NAMES[end]}"
    days = [_day(part) for part in field.split(",")]
    if all(day is not None for day in days):
        return ", ".join(f"{_DAY_NAMES[day]}s" for day in days)
    return None


def schedule_in_words(expression: str | None) -> str:
    parts = str(expression or "").split()
    if len(parts) != 5:
        return f"Custom: {expression or ''}".strip()
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/") and hour == "*" and dom == month == dow == "*":
        return f"Every {minute[2:]} minutes"
    if minute == "0" and hour.startswith("*/") and dom == month == dow == "*":
        return f"Every {hour[2:]} hours"
    if minute.isdigit() and hour == "*" and dom == month == dow == "*":
        return f"Every hour at :{int(minute):02d}"
    if minute.isdigit() and hour.isdigit() and month == "*":
        at = f"{int(hour):02d}:{int(minute):02d}"
        if dom == "*":
            days = _days(dow)
            if days:
                return f"{days} at {at}"
        elif dow == "*" and dom.isdigit():
            return f"Day {int(dom)} of every month at {at}"
    return f"Custom: {expression}"


def next_run_at(expression: str | None, now: datetime | None = None) -> str | None:
    # Imported lazily: the scheduler package imports the agent engine, which imports admin services.
    from ..scheduler.dispatch.cron_schedule import build_cron_trigger

    try:
        trigger = build_cron_trigger(str(expression or ""))
    except ValueError:
        return None
    from datetime import UTC

    current = now or datetime.now(UTC).astimezone()
    fire = trigger.get_next_fire_time(None, current)
    return fire.isoformat() if fire else None


async def last_runs(db: AsyncSession, task_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not task_ids:
        return {}
    latest = (
        select(TaskRun.task_id, func.max(TaskRun.started_at).label("started_at"))
        .where(TaskRun.task_id.in_(task_ids))
        .group_by(TaskRun.task_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(TaskRun.task_id, TaskRun.status, TaskRun.started_at).join(
                latest, (TaskRun.task_id == latest.c.task_id) & (TaskRun.started_at == latest.c.started_at)
            )
        )
    ).all()
    return {
        task_id: {"status": status, "at": started_at.isoformat() if started_at else None}
        for task_id, status, started_at in rows
    }


async def started_by(db: AsyncSession) -> dict[str, list[dict[str, str]]]:
    starts: dict[str, list[dict[str, str]]] = {}
    for scheduler in (await db.execute(select(Scheduler))).scalars():
        starts.setdefault(scheduler.task_id, []).append({
            "kind": "scheduler", "name": scheduler.name or "", "when": schedule_in_words(scheduler.cron_expression),
            "active": "yes" if scheduler.is_active else "no",
        })
    for webhook in (await db.execute(select(Webhook).where(Webhook.task_id.is_not(None)))).scalars():
        starts.setdefault(webhook.task_id, []).append({
            "kind": "webhook", "name": webhook.name or "", "when": "When an alert arrives",
            "active": "yes" if webhook.is_active else "no",
        })
    for task in (await db.execute(select(Task).where(Task.schedule.is_not(None)))).scalars():
        starts.setdefault(task.id, []).append({
            "kind": "action_schedule", "name": "Schedule set on the action", "when": schedule_in_words(task.schedule),
            "active": "yes" if task.is_active else "no",
        })
    return starts


__all__ = [
    "is_work_intake_task",
    "last_runs",
    "next_run_at",
    "schedule_in_words",
    "started_by",
]
