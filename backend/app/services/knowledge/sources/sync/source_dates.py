"""The source's own change date of an item, parsed from what the source already returns (no extra call).

Confluence ``version.when`` (ISO 8601 with ``Z``), Jira ``fields.updated`` (``…+0200``), ServiceNow
``sys_updated_on`` (``YYYY-MM-DD HH:MM:SS`` in UTC with ``sysparm_display_value=false``). An unreadable value is
``None``: the hit then shows when the platform received the item; it never fails the sync.
"""

from __future__ import annotations

from datetime import UTC, datetime


def source_date(value: object) -> datetime | None:
    """An aware UTC datetime, or ``None``."""
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
