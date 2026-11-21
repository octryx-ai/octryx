"""What "narrower" means per field kind. Pure functions, no I/O.

Each rule takes the object's base value, the deviation's value and the field path, and returns the value that
applies in the Workspace:

- ``strict`` (a write): a value that is not narrower raises :class:`DeviationNotNarrowerError` naming the field;
- not strict (a read): a stored deviation that is no longer narrower (the base was narrowed later) is clamped to
  the base, so a read never widens what the object allows.

Kinds:

- **scope**: ``{key: [items]}``; narrower is a subset per key. A base of ``None`` is unrestricted.
- **schedule**: ``{"schedule": preset, "schedule_cron": cron | None}``; narrower is the same schedule or ``manual``
  (``off`` is accepted as ``manual``).
- **level**: ``off`` < ``read`` < ``write``; narrower is the same or lower.
- **flag**: ``true`` → ``false`` only (enabled, write-back).
- **subset**: a list (models); narrower is a subset.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CODE_DEVIATION_NOT_NARROWER = "deviation_not_narrower"
LEVELS = ("off", "read", "write")
SCHEDULE_OFF = "manual"
SCHEDULE_OFF_ALIASES = frozenset({"off", SCHEDULE_OFF})
SCHEDULE_CUSTOM = "custom"


class DeviationNotNarrowerError(ValueError):
    """A deviation that would widen the object (or is no deviation at all); ``field`` is its path."""

    code = CODE_DEVIATION_NOT_NARROWER

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _refuse(field: str, why: str) -> DeviationNotNarrowerError:
    return DeviationNotNarrowerError(field, f"{field} may only narrow the connection: {why}.")


def _items(value: Any, field: str) -> list[str]:
    if not isinstance(value, list | tuple) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise DeviationNotNarrowerError(field, f"{field} must be a list of keys.")
    return list(dict.fromkeys(item.strip() for item in value))


def narrow_scope(base: Mapping[str, list[str]] | None, value: Any, field: str, *, strict: bool) -> dict[str, list]:
    """A subset of ``base`` per key; ``base`` ``None`` admits any keys."""
    if not isinstance(value, Mapping):
        raise DeviationNotNarrowerError(field, f"{field} must be an object of key lists.")
    narrowed: dict[str, list[str]] = {}
    for key, raw in value.items():
        items = _items(raw, f"{field}.{key}")
        if base is None:
            narrowed[str(key)] = items
            continue
        allowed = {item.upper() for item in base.get(str(key)) or ()}
        outside = [item for item in items if item.upper() not in allowed]
        if outside and strict:
            raise _refuse(f"{field}.{key}", "every key must be within the connection's scope")
        narrowed[str(key)] = [item for item in items if item.upper() in allowed]
    if base is not None:
        # A key the deviation leaves out keeps the base's list.
        narrowed = {**{key: list(items) for key, items in base.items()}, **narrowed}
    return narrowed


def _schedule_pair(value: Mapping[str, Any]) -> tuple[str, str | None]:
    preset = str(value.get("schedule") or "").strip()
    preset = SCHEDULE_OFF if preset in SCHEDULE_OFF_ALIASES else preset
    cron = " ".join(str(value.get("schedule_cron") or "").split()) or None
    return preset, cron if preset == SCHEDULE_CUSTOM else None


def narrow_schedule(base: Mapping[str, Any], value: Mapping[str, Any], field: str, *, strict: bool) -> dict:
    """The same schedule as the base, or ``manual``."""
    wanted = _schedule_pair(value)
    current = _schedule_pair(base)
    if wanted[0] == SCHEDULE_OFF or wanted == current:
        return {"schedule": wanted[0], "schedule_cron": wanted[1]}
    if strict:
        raise _refuse(field, "the schedule may only stay the same or be turned off (manual)")
    return {"schedule": current[0], "schedule_cron": current[1]}


def narrow_level(base: str, value: Any, field: str, *, strict: bool) -> str:
    """The same level or a lower one (``off`` < ``read`` < ``write``)."""
    if value not in LEVELS:
        raise DeviationNotNarrowerError(field, f"{field} must be one of: {', '.join(LEVELS)}.")
    base_rank = LEVELS.index(base) if base in LEVELS else 0
    if LEVELS.index(value) <= base_rank:
        return str(value)
    if strict:
        raise _refuse(field, "the level may only be the same or lower")
    return LEVELS[base_rank]


def _flag(value: Any, field: str) -> bool:
    if isinstance(value, Mapping) and set(value) <= {"enabled"} and isinstance(value.get("enabled"), bool):
        return bool(value["enabled"])
    if isinstance(value, bool):
        return value
    raise DeviationNotNarrowerError(field, f"{field} must be true or false.")


def narrow_flag(base: Any, value: Any, field: str, *, strict: bool) -> bool:
    """``true`` → ``false`` only; ``base`` may be a bool or ``{"enabled": bool, ...}``."""
    allowed = bool(base.get("enabled")) if isinstance(base, Mapping) else bool(base)
    wanted = _flag(value, field)
    if wanted and not allowed:
        if strict:
            raise _refuse(field, "it can only be switched off")
        return False
    return wanted


def narrow_subset(base: list[str] | None, value: Any, field: str, *, strict: bool) -> list[str]:
    """A subset of ``base`` (``None`` admits any)."""
    items = _items(value, field)
    if base is None:
        return items
    outside = [item for item in items if item not in base]
    if outside and strict:
        raise _refuse(field, "every entry must already be allowed")
    return [item for item in items if item in base]


__all__ = [
    "CODE_DEVIATION_NOT_NARROWER",
    "LEVELS",
    "SCHEDULE_CUSTOM",
    "SCHEDULE_OFF",
    "DeviationNotNarrowerError",
    "narrow_flag",
    "narrow_level",
    "narrow_schedule",
    "narrow_scope",
    "narrow_subset",
]
