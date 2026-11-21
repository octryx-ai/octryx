"""One wire format for every Knowledge connector and run time.

Stored times are naive UTC (``time_utils.utc_now``), in columns and in the cursor JSON. Every
response carries them as ISO 8601 with an explicit ``+00:00`` offset, so a browser never reads
them as local time.
"""

from __future__ import annotations

from datetime import datetime

from .....time_utils import ensure_utc


def utc_iso(value: datetime | str | None) -> str | None:
    """``value`` (a datetime or a stored ISO string; naive means UTC) as ISO 8601 with ``+00:00``.

    ``None`` for no value or a stored string that is not an ISO time.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return ensure_utc(value).isoformat()


__all__ = ["utc_iso"]
