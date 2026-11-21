"""Cron trigger construction, validation and next-run preview for schedulers.

One builder serves registration (``registration.py``) and the admin preview, so
the preview parses exactly what the scheduler registers: APScheduler 3 crontab syntax,
numeric weekdays counting from Monday = 0, day-of-month AND day-of-week, and the process
local zone APScheduler applies when no zone is given. Nothing here changes those semantics.

The preview is calculated trigger times, not observed execution. It never touches the
database, the running scheduler or a job. When the engine's own sequence repeats or goes
backwards, the preview stops there and says so instead of inventing times. Measured with
APScheduler 3.11.2 and the scheduler's own call pattern: at spring-forward a time inside
the gap fires once, an hour later in wall time (``dst_gap``); at fall-back a wall time in
the repeated hour fires twice, once per offset (``dst_repeat``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from tzlocal import get_localzone

from ...runtime_toggles import background_workers_enabled
from ...time_utils import utc_now_aware

MAX_CRON_LENGTH = 100  # Scheduler.cron_expression is String(100).
MAX_PREVIEW_COUNT = 10
_FIELDS = (
    ("minute", "minute"),
    ("hour", "hour"),
    ("day", "day of month"),
    ("month", "month"),
    ("day_of_week", "day of week"),
)


@dataclass(frozen=True)
class CronProblem:
    code: str
    message: str
    field: str | None = None

    def as_detail(self) -> dict[str, str]:
        detail = {"code": self.code, "message": self.message}
        if self.field:
            detail["field"] = self.field
        return detail


NEVER_FIRES = CronProblem("cron_never_fires", "This schedule never fires: no date matches all of its fields.")
SEQUENCE_WARNING = {
    "code": "engine_sequence_not_increasing",
    "message": (
        "Around a daylight-saving change the scheduler repeats or steps back in time. "
        "Only the times before that point are shown."
    ),
}


def build_cron_trigger(expression: str) -> CronTrigger:
    """The trigger the scheduler registers: no explicit zone, so APScheduler uses the process zone."""
    return CronTrigger.from_crontab(expression)


def check_cron_syntax(expression: Any) -> tuple[CronTrigger | None, CronProblem | None]:
    """Cheap syntax check of the exact value; returns the built trigger when it parses."""
    if not isinstance(expression, str) or not expression.strip():
        return None, CronProblem("cron_required", "Enter a schedule.")
    if len(expression) > MAX_CRON_LENGTH:
        return None, CronProblem("cron_too_long", f"A cron expression has at most {MAX_CRON_LENGTH} characters.")
    values = expression.split()
    if len(values) != len(_FIELDS):
        return None, CronProblem(
            "cron_field_count",
            "A cron expression has five fields: minute, hour, day of month, month, day of week.",
        )
    for (field, label), value in zip(_FIELDS, values, strict=True):
        try:
            CronTrigger(**{field: value}, timezone=UTC)
        except ValueError:
            hint = " Use the names mon–sun, or 0–6 counting from Monday = 0." if field == "day_of_week" else ""
            return None, CronProblem("cron_field_invalid", f"The {label} field is not valid.{hint}", field)
    try:
        return build_cron_trigger(expression), None
    except ValueError:
        return None, CronProblem("cron_invalid", "The cron expression is not valid.")


def _schedulable_problem(expression: Any, now: datetime) -> CronProblem | None:
    trigger, problem = check_cron_syntax(expression)
    if problem is not None:
        return problem
    # Proving "never" makes APScheduler scan to year 9999 (~50-180 ms): callers run this off the event loop.
    return NEVER_FIRES if trigger.get_next_fire_time(None, now) is None else None


async def require_schedulable_cron(expression: Any, *, field: str = "cron_expression") -> None:
    """Typed 422 before any write when a submitted expression cannot be scheduled.

    ``field`` names the request field in the error: schedulers submit ``cron_expression``, tasks ``schedule``.
    """
    problem = await asyncio.to_thread(_schedulable_problem, expression, utc_now_aware())
    if problem is not None:
        raise HTTPException(status_code=422, detail={**problem.as_detail(), "field": field})


def scheduling_scope() -> dict[str, str]:
    """Which process this preview speaks for, from the existing background-worker toggle only."""
    if background_workers_enabled():
        return {
            "owner": "this_process",
            "message": "This server process registers schedules, in the time zone shown.",
        }
    return {
        "owner": "separate_worker",
        "message": (
            "Schedules are registered by a separate scheduler worker. Its time zone and when it applies "
            "a change are not confirmed here; the times shown use this server process's zone."
        ),
    }


def _zone_name(zone: tzinfo) -> str:
    return str(getattr(zone, "key", None) or zone)


def _preview(expression: Any, count: int, now: datetime) -> dict[str, Any]:
    trigger, problem = check_cron_syntax(expression)
    zone = trigger.timezone if trigger is not None else get_localzone()
    result: dict[str, Any] = {
        "valid": False,
        "cron_expression": expression,
        "timezone": {"name": _zone_name(zone), "source": "process_local"},
        "scheduling": scheduling_scope(),
        "next_runs": [],
        "truncated": False,
        "warning": None,
        "error": problem.as_detail() if problem else None,
    }
    if trigger is None:
        return result
    runs: list[dict[str, Any]] = []
    shown_wall_times: set[datetime] = set()
    previous: datetime | None = None
    for _ in range(count):
        # The same (previous fire, now) arguments the scheduler passes after each run.
        fire = trigger.get_next_fire_time(previous, previous or now)
        if fire is None:
            break
        # Compare instants in UTC: datetimes sharing one tzinfo compare by wall time, which repeats at fall-back.
        fire_utc = fire.astimezone(UTC)
        if previous is not None and fire_utc <= previous.astimezone(UTC):
            # The engine repeats or steps back: stop rather than invent a sequence.
            result["truncated"] = True
            result["warning"] = SEQUENCE_WARNING
            break
        # Rendered from the instant; astimezone(zone) on a datetime already in that zone would keep its label.
        local = fire_utc.astimezone(zone)
        wall_time = local.replace(tzinfo=None)
        runs.append(
            {
                "at_utc": fire_utc.isoformat().replace("+00:00", "Z"),
                "local": local.isoformat(),
                # Inside a spring-forward gap the engine labels the instant with a wall time that does not exist.
                "dst_gap": fire.replace(tzinfo=None) != wall_time,
                # After clocks go back the engine fires the repeated wall time again (once per offset).
                "dst_repeat": wall_time in shown_wall_times,
            }
        )
        shown_wall_times.add(wall_time)
        previous = fire
    if not runs:
        result["error"] = NEVER_FIRES.as_detail()
        return result
    result["valid"] = True
    result["next_runs"] = runs
    return result


async def preview_schedule(expression: Any, count: int = 5, *, now: datetime | None = None) -> dict[str, Any]:
    """Next calculated fire times for an expression: pure, bounded and off the event loop."""
    bounded = max(1, min(int(count), MAX_PREVIEW_COUNT))
    return await asyncio.to_thread(_preview, expression, bounded, now or utc_now_aware())


__all__ = [
    "MAX_CRON_LENGTH",
    "MAX_PREVIEW_COUNT",
    "NEVER_FIRES",
    "CronProblem",
    "build_cron_trigger",
    "check_cron_syntax",
    "preview_schedule",
    "require_schedulable_cron",
    "scheduling_scope",
]
