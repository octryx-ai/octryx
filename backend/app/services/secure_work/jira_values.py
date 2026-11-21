from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


def name_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return blank_to_none(value.get("name") or value.get("value") or value.get("key") or value.get("id"))
    return blank_to_none(value)


def user_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return blank_to_none(
            value.get("accountId")
            or value.get("name")
            or value.get("key")
            or value.get("emailAddress")
            or value.get("displayName")
        )
    return blank_to_none(value)


def project_key(issue: dict[str, Any], fields: dict[str, Any]) -> str | None:
    explicit = issue.get("project_key") or fields.get("project_key")
    if explicit:
        return blank_to_none(explicit)
    project = issue.get("project") or fields.get("project")
    if isinstance(project, dict):
        return blank_to_none(project.get("key") or project.get("name") or project.get("id"))
    return blank_to_none(project)


def parent_key(issue: dict[str, Any], fields: dict[str, Any]) -> str | None:
    parent = issue.get("parent") or fields.get("parent")
    if isinstance(parent, dict):
        return blank_to_none(parent.get("key") or parent.get("id"))
    return blank_to_none(issue.get("parent_key") or fields.get("parent_key") or parent)


def watchers(value: Any) -> list[str]:
    if isinstance(value, dict):
        raw = value.get("watchers") or value.get("items") or value.get("values")
    else:
        raw = value
    return [normalized for item in list_value(raw) if (normalized := user_value(item))]


def source_url(issue: dict[str, Any]) -> str | None:
    value = issue.get("url") or issue.get("browse_url") or issue.get("self")
    return blank_to_none(value)


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def object_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        return []
    values: list[str] = []
    for item in raw_values:
        normalized = str(item or "").strip()
        if normalized:
            values.append(normalized)
    return values


def blank_to_none(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def optional_int(value: Any) -> int | None:
    if value in {None, ""} or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # Persisted datetimes are naive UTC everywhere (utc_now); an offset-aware
    # source timestamp (Jira sends local time with offset) is converted to UTC,
    # not just stripped, so staleness comparisons do not shift by the source
    # offset.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
