"""The person's own pet settings, in ``<state dir>/pet.json`` (no quiet hours by default; the person
sets them in the pet's settings, nothing is hard-coded).

``{"notifications": true, "quiet_hours": {"enabled": false, "start": "19:00", "end": "08:00"}}``

Quiet hours use the computer's local time. During them, and while the platform reports the person's companion quiet
hours (``quiet.active``), the pet shows its state but sends no notification. A broken file falls back to the
defaults; it is never rewritten without a change from the person.

Start at login (on by default, the person can turn it off any time): the installers turn it on;
``pet disable`` or "Turn off Octryx" in the menu leaves the file ``<root>/pet-autostart-off``, which every later
install and update respects until ``pet enable``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, time
from pathlib import Path
from typing import Any

from ..state import read_json, write_private_json

FILE_NAME = "pet.json"
AUTOSTART_OFF_FILE = "pet-autostart-off"
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class QuietHours:
    enabled: bool = False
    start: str = "19:00"
    end: str = "08:00"

    def label(self) -> str:
        return f"{self.start}–{self.end}"

    def active(self, now: datetime) -> bool:
        if not self.enabled or self.start == self.end:
            return False
        start, end, clock = _time(self.start), _time(self.end), now.time().replace(second=0, microsecond=0)
        return start <= clock < end if start < end else clock >= start or clock < end


@dataclass(frozen=True)
class PetSettings:
    notifications: bool = True
    quiet_hours: QuietHours = QuietHours()


def _time(hhmm: str) -> time:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return time(hour, minute)


def valid_hhmm(value: Any) -> bool:
    return isinstance(value, str) and bool(_HHMM.match(value))


def parse_window(text: str) -> tuple[str, str] | None:
    """``"19:00-08:00"`` → ``("19:00", "08:00")``; ``None`` when it is not two HH:MM times."""
    parts = [part.strip() for part in re.split(r"[-–]", text or "")]
    if len(parts) != 2 or not all(valid_hhmm(part) for part in parts) or parts[0] == parts[1]:
        return None
    return parts[0], parts[1]


def from_dict(value: dict[str, Any]) -> PetSettings:
    quiet = value.get("quiet_hours") if isinstance(value.get("quiet_hours"), dict) else {}
    hours = QuietHours()
    if valid_hhmm(quiet.get("start")) and valid_hhmm(quiet.get("end")) and quiet["start"] != quiet["end"]:
        hours = QuietHours(enabled=quiet.get("enabled") is True, start=quiet["start"], end=quiet["end"])
    return PetSettings(notifications=value.get("notifications") is not False, quiet_hours=hours)


def to_dict(settings: PetSettings) -> dict[str, Any]:
    hours = settings.quiet_hours
    return {"notifications": settings.notifications,
            "quiet_hours": {"enabled": hours.enabled, "start": hours.start, "end": hours.end}}


def load(root: Path) -> PetSettings:
    return from_dict(read_json(root / FILE_NAME))


def save(root: Path, settings: PetSettings) -> None:
    write_private_json(root / FILE_NAME, to_dict(settings))


def with_quiet_hours(settings: PetSettings, *, enabled: bool, window: tuple[str, str] | None = None) -> PetSettings:
    hours = settings.quiet_hours
    start, end = window or (hours.start, hours.end)
    return replace(settings, quiet_hours=QuietHours(enabled=enabled, start=start, end=end))


def autostart_off(root: Path) -> bool:
    """The person turned the pet off (``pet disable`` or the menu); installs and updates leave it off."""
    return (root / AUTOSTART_OFF_FILE).exists()


def set_autostart_off(root: Path, off: bool) -> None:
    marker = root / AUTOSTART_OFF_FILE
    if off:
        root.mkdir(parents=True, exist_ok=True)
        marker.touch()
    else:
        marker.unlink(missing_ok=True)


__all__ = ["AUTOSTART_OFF_FILE", "PetSettings", "QuietHours", "autostart_off", "load", "parse_window", "save",
           "set_autostart_off", "with_quiet_hours"]
