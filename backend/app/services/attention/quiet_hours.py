"""Quiet hours of the companion: when they are active, and their validated shape."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT = {"enabled": False, "start": "19:00", "end": "08:00", "timezone": "Europe/Zurich"}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class QuietHoursError(ValueError):
    pass


def normalize(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QuietHoursError("quiet_hours is an object")
    merged = {**DEFAULT, **{key: value[key] for key in DEFAULT if key in value}}
    if type(merged["enabled"]) is not bool:
        raise QuietHoursError("quiet_hours.enabled is true or false")
    for key in ("start", "end"):
        if not isinstance(merged[key], str) or not _HHMM.match(merged[key]):
            raise QuietHoursError(f"quiet_hours.{key} is HH:MM")
    try:
        ZoneInfo(str(merged["timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise QuietHoursError("quiet_hours.timezone is an IANA time zone") from exc
    return merged


def _at(day: datetime, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime.combine(day.date(), time(hour, minute), tzinfo=day.tzinfo)


def quiet_state(value: Any, *, now: datetime) -> dict[str, Any]:
    """``{active, until}``: whether ``now`` (aware) lies in the quiet window, and when it ends (ISO)."""
    try:
        hours = normalize(value) if value else None
    except QuietHoursError:
        hours = None
    if not hours or not hours["enabled"]:
        return {"active": False, "until": None}
    local = now.astimezone(ZoneInfo(hours["timezone"]))
    start, end = _at(local, hours["start"]), _at(local, hours["end"])
    if start <= end:  # a window within one day
        active, until = start <= local < end, end
    elif local >= start:  # over midnight, evening part
        active, until = True, end + timedelta(days=1)
    else:  # over midnight, morning part
        active, until = local < end, end
    return {"active": active, "until": until.isoformat() if active else None}


__all__ = ["DEFAULT", "QuietHoursError", "normalize", "quiet_state"]
