"""The source's own change date of an item, parsed from what the source already returns (no extra call). An unreadable
value is ``None`` and never fails the sync."""

from __future__ import annotations

from datetime import UTC, datetime


def source_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


__all__ = ["source_date"]
