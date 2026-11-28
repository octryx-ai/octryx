"""The configuration of a Custom REST intake, validated and refused, never cleaned up."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from ..intake.schedule import ScheduleError, normalize_schedule
from ..workflow_mapping import DEFAULT_WORKFLOW_STATES

SOURCE_TYPE = "custom_rest"
LABEL = "Custom REST"
REQUIRED_FIELDS = ("key", "title", "status")
OPTIONAL_FIELDS = ("id", "description", "type", "priority", "reporter", "assignee", "url", "parent", "labels",
                   "updated_at", "created_at")
FIELDS = (*REQUIRED_FIELDS, *OPTIONAL_FIELDS)
TEMPLATE_KEYS = ("source_key", "source_id", "target_status", "to_state")
DEFAULT_SCHEDULE = {"preset": "every_15_min", "cron": None}
DEFAULT_MAX_ITEMS, MAX_MAX_ITEMS = 5000, 100000
DEFAULT_MAX_PAGES, MAX_MAX_PAGES = 100, 10000
MAX_STATUS_CHARS = 120
PATH_RE = re.compile(r"^[A-Za-z0-9_$@:-]+(\.[A-Za-z0-9_$@:-]+)*$")
_WORK_STATES = frozenset(state["key"] for state in DEFAULT_WORKFLOW_STATES)


def refused(field: str, message: str, code: str = "invalid_request") -> HTTPException:
    return HTTPException(status_code=422, detail={"state": "invalid_request", "code": code, "field": field,
                                                  "message": f"{field} {message}"})


def _status(raw: object, field: str) -> str:
    if type(raw) is not str or not raw.strip() or len(raw.strip()) > MAX_STATUS_CHARS or not raw.isprintable():
        raise refused(field, f"must hold non-empty printable statuses of at most {MAX_STATUS_CHARS} characters")
    return " ".join(raw.split())


def status_key(raw: object) -> str:
    return " ".join(str(raw).split()).casefold() if raw not in (None, "") else ""


def _bounded(raw: object, default: int, high: int, field: str) -> int:
    value = default if raw in (None, "") else raw
    if type(value) is not int or not 1 <= value <= high:
        raise refused(field, f"must be an integer from 1 to {high}")
    return value


def _fields(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise refused("how.field_mapping", "must map Work item fields to dotted record paths")
    unknown = sorted(str(key) for key in raw if key not in FIELDS)
    if unknown:
        raise refused("how.field_mapping", f"names unknown fields: {', '.join(unknown)} (known: {', '.join(FIELDS)})")
    fields: dict[str, str] = {}
    for name, path in raw.items():
        if path in (None, ""):
            continue
        if not isinstance(path, str) or not PATH_RE.fullmatch(path.strip()):
            raise refused(f"how.field_mapping.{name}", "must be a dotted record path")
        fields[str(name)] = path.strip()
    missing = [name for name in REQUIRED_FIELDS if name not in fields]
    if missing:
        raise refused("how.field_mapping", f"needs {', '.join(missing)}: a record without a stable key, a title "
                                           "and a status cannot become a Work item")
    return fields


def _state_mapping(raw: object) -> dict[str, str]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise refused("how.status_mapping", "must be an object of source status to work state")
    mapping: dict[str, str] = {}
    for status, target in raw.items():
        if target not in _WORK_STATES:
            raise refused("how.status_mapping", f"maps {_status(status, 'how.status_mapping')!r} to an unknown "
                                                "work state")
        mapping[status_key(_status(status, "how.status_mapping"))] = str(target)
    return mapping


def _closed(raw: object) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise refused("how.closed_statuses", "must be a list of status names")
    return sorted({_status(status, "how.closed_statuses") for status in raw}, key=str.casefold)


def _arguments(raw: object, field: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise refused(field, "must be an object of argument names and values")
    return {str(name): value for name, value in raw.items()}


def _write_back(raw: object) -> dict[str, Any] | None:
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, Mapping) or not str(raw.get("operation") or "").strip():
        raise refused("how.write_back", "needs the write operation of the same API")
    body = raw.get("body")
    if body is not None and not isinstance(body, Mapping):
        raise refused("how.write_back.body", "must be a JSON object template")
    return {"operation": str(raw["operation"]).strip(),
            "arguments": _arguments(raw.get("arguments"), "how.write_back.arguments"),
            **({"body": dict(body)} if body is not None else {})}


def _schedule(raw: object) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_SCHEDULE)
    try:
        return normalize_schedule(raw)
    except ScheduleError as error:
        raise refused("schedule", str(error)) from None


def normalize_config(what: Mapping[str, Any], how: Mapping[str, Any], schedule: object) -> dict[str, Any]:
    operation = str(what.get("operation") or "").strip()
    if not operation:
        raise refused("what.operation", "is required: the list operation of the API")
    role = what.get("role")
    if role is not None and (not isinstance(role, str) or len(role.strip()) > 80):
        raise refused("what.role", "must be the name of an Octryx role")
    auto = how.get("auto_analyze_new", False)
    if type(auto) is not bool:
        raise refused("how.auto_analyze_new", "must be a boolean")
    return {
        "operation": operation,
        "role": role.strip() if isinstance(role, str) and role.strip() else None,
        "arguments": _arguments(what.get("arguments"), "what.arguments"),
        "fields": _fields(how.get("field_mapping")),
        "state_mapping": _state_mapping(how.get("status_mapping")),
        "closed_statuses": _closed(how.get("closed_statuses")),
        "schedule": _schedule(schedule),
        "max_items": _bounded(what.get("max_items"), DEFAULT_MAX_ITEMS, MAX_MAX_ITEMS, "what.max_items"),
        "max_pages": _bounded(what.get("max_pages"), DEFAULT_MAX_PAGES, MAX_MAX_PAGES, "what.max_pages"),
        "auto_analyze_new": auto,
        "write_back": _write_back(how.get("write_back")),
    }


def intake_of_row(row: Any) -> dict[str, Any]:
    filters = dict(row.filters_json or {})
    mapping = dict(row.field_mapping_json or {})
    options = dict(row.sync_options_json or {})
    return {
        "definition": str(row.source_instance or row.connection_id or ""),
        "operation": str(filters.get("operation") or ""),
        "role": filters.get("role") or None,
        "arguments": dict(filters.get("arguments") or {}),
        "fields": dict(mapping.get("fields") or {}),
        "state_mapping": dict(mapping.get("state_mapping") or {}),
        "closed_statuses": list(mapping.get("closed_statuses") or []),
        "schedule": options.get("schedule") or dict(DEFAULT_SCHEDULE),
        "max_items": int(options.get("max_items") or DEFAULT_MAX_ITEMS),
        "max_pages": int(options.get("max_pages") or DEFAULT_MAX_PAGES),
        "auto_analyze_new": bool(options.get("auto_analyze_new")),
        "write_back": options.get("write_back") or None,
    }


def mapped_state(status: object, intake: Mapping[str, Any]) -> tuple[str, str]:
    target = dict(intake.get("state_mapping") or {}).get(status_key(status))
    return (target, "configured") if target else ("intake", "unmapped")


def is_closed(status: object, intake: Mapping[str, Any]) -> bool:
    return bool(status_key(status)) and status_key(status) in {status_key(name) for name in
                                                               intake.get("closed_statuses") or ()}


__all__ = [
    "FIELDS",
    "LABEL",
    "REQUIRED_FIELDS",
    "SOURCE_TYPE",
    "TEMPLATE_KEYS",
    "intake_of_row",
    "is_closed",
    "mapped_state",
    "normalize_config",
    "refused",
    "status_key",
]
