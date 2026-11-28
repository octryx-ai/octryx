"""One wire format for every Knowledge connector and run time: ISO 8601 with an explicit ``+00:00`` offset."""

from __future__ import annotations

from datetime import datetime

from .....time_utils import ensure_utc


def utc_iso(value: datetime | str | None) -> str | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return ensure_utc(value).isoformat()


__all__ = ["utc_iso"]
