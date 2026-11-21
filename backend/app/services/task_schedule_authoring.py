"""Validation of a submitted ``Task.schedule`` before any write.

Every writer of ``Task.schedule`` (admin panel, REST and package import) calls
:func:`require_task_schedule` before it creates or changes a task. A schedule is
validated with the scheduler's own cron rules (``scheduler/dispatch/cron_schedule.py``), so a
value that is saved is also a value the scheduler registers and that fires.

* ``None`` and ``""`` remove the schedule. They are never validated, and each writer keeps storing
  them (``None`` or ``""``).
* Any other value must be a string and a schedulable five-field cron expression. It is stored exactly
  as submitted: no trimming, no weekday or time zone reinterpretation.
* A raw non-string value (``0``, ``False``, ``[]``, ``{}`` ...) is refused; truthiness never turns it
  into a removal.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

SCHEDULE_FIELD = "schedule"

__all__ = ["require_task_schedule"]


def _is_removal(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _require_text(value: Any) -> None:
    if not isinstance(value, str):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "schedule_not_text",
                "message": "A schedule must be text: a five-field cron expression.",
                "field": SCHEDULE_FIELD,
            },
        )


async def require_task_schedule(value: Any) -> None:
    """Refuse a submitted schedule that is neither a removal nor a schedulable cron string."""
    if _is_removal(value):
        return
    _require_text(value)
    # Imported here: ``app.scheduler`` imports the agent runtime, which imports the task services.
    from ..scheduler.dispatch.cron_schedule import require_schedulable_cron

    await require_schedulable_cron(value, field=SCHEDULE_FIELD)
