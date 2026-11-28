"""One schedule list for both uses: ``manual`` | ``every_15_min`` | ``hourly`` | ``every_4_hours`` | ``daily_0600`` |
``custom`` (+ ``schedule_cron``), as the intake presets (``secure_work/intake/schedule.py``)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from ..secure_work.intake.schedule import CUSTOM, MANUAL, PRESETS
from .contract import CODE_SCHEDULE_CRON_INVALID, CODE_SCHEDULE_INVALID, invalid

MIN_INTERVAL = timedelta(minutes=15)
PRESET_MINUTES = {"every_15_min": 15, "hourly": 60, "every_4_hours": 240, "daily_0600": 1440}
_MINUTE_INTERVAL = re.compile(r"^\*/(\d{1,2}) \* \* \* \*$")
_HOUR_INTERVAL = re.compile(r"^0 \*/(\d{1,2}) \* \* \*$")


def _cron_text(raw: Any) -> str:
    return " ".join(str(raw or "").split())


def validate_cron(raw: Any, field: str) -> str:
    cron = _cron_text(raw)
    message = f"{field} must be a five-field cron that runs at most every 15 minutes."
    if len(cron.split(" ")) != 5:
        raise invalid(field, message, CODE_SCHEDULE_CRON_INVALID)
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=UTC)
    except ValueError:
        raise invalid(field, message, CODE_SCHEDULE_CRON_INVALID) from None
    fire = trigger.get_next_fire_time(None, datetime(2026, 1, 5, tzinfo=UTC))
    for _ in range(200):  # a week of 15-minute slots is far more than any gap check needs
        following = trigger.get_next_fire_time(fire, fire + timedelta(seconds=1)) if fire else None
        if fire is None or following is None:
            break
        if following - fire < MIN_INTERVAL:
            raise invalid(field, message, CODE_SCHEDULE_CRON_INVALID)
        fire = following
    return cron


def normalize(use: str, payload: dict[str, Any]) -> dict[str, Any]:
    preset = str(payload.get("schedule") or "").strip()
    preset = MANUAL if preset == "off" else preset
    if preset not in PRESETS:
        raise invalid(f"uses.{use}.schedule", f"uses.{use}.schedule must be one of: {', '.join(PRESETS)}.",
                      CODE_SCHEDULE_INVALID)
    if preset != CUSTOM:
        return {"schedule": preset, "schedule_cron": None}
    return {"schedule": CUSTOM, "schedule_cron": validate_cron(payload.get("schedule_cron"),
                                                               f"uses.{use}.schedule_cron")}


def intake_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    return {"preset": schedule["schedule"], "cron": schedule["schedule_cron"]}


def from_intake(stored: dict[str, Any]) -> dict[str, Any]:
    return {"schedule": stored.get("preset") or MANUAL, "schedule_cron": stored.get("cron")}


def from_knowledge(enabled: bool, minutes: int | None) -> dict[str, Any]:
    if not enabled:
        return {"schedule": MANUAL, "schedule_cron": None}
    minutes = int(minutes or 0)
    for preset, preset_minutes in PRESET_MINUTES.items():
        if preset_minutes == minutes:
            return {"schedule": preset, "schedule_cron": None}
    if 0 < minutes < 60 and 60 % minutes == 0:
        return {"schedule": CUSTOM, "schedule_cron": f"*/{minutes} * * * *"}
    if minutes % 60 == 0 and 0 < minutes // 60 < 24 and 24 % (minutes // 60) == 0:
        return {"schedule": CUSTOM, "schedule_cron": f"0 */{minutes // 60} * * *"}
    return {"schedule": CUSTOM, "schedule_cron": None}


def knowledge_interval(schedule: dict[str, Any]) -> tuple[bool, int | None]:
    preset = schedule["schedule"]
    if preset == MANUAL:
        return False, None
    if preset in PRESET_MINUTES:
        return True, PRESET_MINUTES[preset]
    cron = str(schedule.get("schedule_cron") or "")
    minute, hour = _MINUTE_INTERVAL.match(cron), _HOUR_INTERVAL.match(cron)
    if minute and 60 % int(minute.group(1)) == 0:
        return True, int(minute.group(1))
    if hour and 0 < int(hour.group(1)) < 24 and 24 % int(hour.group(1)) == 0:
        return True, int(hour.group(1)) * 60
    raise invalid("uses.knowledge.schedule_cron",
                  "Knowledge sources run on a fixed interval: use */n minutes or 0 */h hours.",
                  CODE_SCHEDULE_CRON_INVALID)


__all__ = [
    "from_intake",
    "from_knowledge",
    "intake_schedule",
    "knowledge_interval",
    "normalize",
    "validate_cron",
]
