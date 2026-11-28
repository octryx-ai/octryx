"""Validation of a submitted ``Task.schedule`` before any write. Checked with the scheduler's own cron rules, so a saved
value is one the scheduler runs."""

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
    if _is_removal(value):
        return
    _require_text(value)
    # Imported here: ``app.scheduler`` imports the agent runtime, which imports the task services.
    from ..scheduler.dispatch.cron_schedule import require_schedulable_cron

    await require_schedulable_cron(value, field=SCHEDULE_FIELD)
