"""One schedule value per intake: a preset, or a custom cron under Advanced.

Presets: ``manual`` (no schedule), ``every_minute`` (incremental syncs make it cheap),
``every_15_min``, ``hourly``, ``every_4_hours``, ``daily_0600``; ``custom``
carries its own ``cron``. Options without a ``schedule`` read as ``manual``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apscheduler.triggers.cron import CronTrigger

MANUAL = "manual"
CUSTOM = "custom"
PRESET_CRONS = {
    "every_minute": "* * * * *",
    "every_15_min": "*/15 * * * *",
    "hourly": "0 * * * *",
    "every_4_hours": "0 */4 * * *",
    "daily_0600": "0 6 * * *",
}
PRESETS = (MANUAL, *PRESET_CRONS, CUSTOM)


class ScheduleError(ValueError):
    """A refused schedule; the message names the field, never a value."""


def schedule_of(options: Mapping[str, Any] | None) -> dict[str, Any]:
    """``{preset, cron}`` of sync options (the ``schedule`` value, else ``manual``)."""
    stored = dict(options or {}).get("schedule")
    if isinstance(stored, Mapping) and stored.get("preset") in PRESETS:
        cron = str(stored.get("cron") or "").strip() or None
        return {"preset": stored["preset"], "cron": cron if stored["preset"] == CUSTOM else None}
    return {"preset": MANUAL, "cron": None}


def normalize_schedule(raw: object) -> dict[str, Any]:
    """The validated ``{preset, cron}``; raises :class:`ScheduleError`."""
    if not isinstance(raw, Mapping) or raw.get("preset") not in PRESETS:
        raise ScheduleError(f"schedule.preset must be one of: {', '.join(PRESETS)}")
    preset = raw["preset"]
    if preset != CUSTOM:
        return {"preset": preset, "cron": None}
    cron = " ".join(str(raw.get("cron") or "").split())
    try:
        CronTrigger.from_crontab(cron)
    except ValueError:
        raise ScheduleError("schedule.cron must be a five-field cron expression") from None
    return {"preset": CUSTOM, "cron": cron}


def with_schedule(options: Mapping[str, Any] | None, schedule: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``options`` with one ``schedule`` (the given one validated, else the stored one)."""
    merged = dict(options or {})
    merged["schedule"] = normalize_schedule(schedule) if schedule is not None else schedule_of(merged)
    return merged


def cron_of(schedule: Mapping[str, Any]) -> str | None:
    """The cron the scheduler runs; ``None`` for ``manual``."""
    preset = schedule.get("preset")
    if preset == CUSTOM:
        return str(schedule.get("cron") or "") or None
    return PRESET_CRONS.get(str(preset))


__all__ = ["CUSTOM", "MANUAL", "PRESETS", "PRESET_CRONS", "ScheduleError", "cron_of",
           "normalize_schedule", "schedule_of", "with_schedule"]
