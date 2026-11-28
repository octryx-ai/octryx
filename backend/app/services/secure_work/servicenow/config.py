"""The per-Workspace ServiceNow intake configuration, stored as a ``WorkItemSyncConfig``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from ...knowledge.ledger.errors import InvalidEvidenceRequestError
from ...knowledge.sources.sync.servicenow_scope import validate_encoded_query
from ...servicenow_record_limit import FIELDS, RecordLimitError, normalize_entries
from ..intake.schedule import ScheduleError, normalize_schedule
from ..workflow_mapping import DEFAULT_WORKFLOW_STATES

SOURCE_TYPE = "servicenow"
TABLES = ("incident", "change_request")
DEFAULT_EXCLUDED_STATES = ("Closed", "Resolved", "Cancelled", "Canceled")
DEFAULT_STATE_MAPPING = {
    "new": "intake",
    "in progress": "development",
    "on hold": "blocked",
    "resolved": "done",
    "closed": "done",
    "cancelled": "done",
    "canceled": "done",
}
DEFAULT_SCHEDULE = {"preset": "every_15_min", "cron": None}
DEFAULT_MAX_ITEMS = 200
MAX_MAX_ITEMS = 1000
MAX_STATE_CHARS = 80
_WORK_STATES = frozenset(state["key"] for state in DEFAULT_WORKFLOW_STATES)


def refused(field: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"state": "invalid_request", "field": field, "reason": message})


_refuse = refused


def _state_name(raw: object, field: str) -> str:
    if type(raw) is not str or not raw.strip() or len(raw.strip()) > MAX_STATE_CHARS or not raw.isprintable():
        raise _refuse(field, "a state must be a non-empty printable name of at most 80 characters")
    return " ".join(raw.split())


def _bounded(raw: object, default: int, low: int, high: int, field: str) -> int:
    value = default if raw is None else raw
    if type(value) is not int or not low <= value <= high:
        raise _refuse(field, f"must be an integer from {low} to {high}")
    return value


def _schedule(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schedule") is None:
        return dict(DEFAULT_SCHEDULE)
    try:
        return normalize_schedule(payload.get("schedule"))
    except ScheduleError as error:
        raise _refuse("schedule", str(error)) from None


def normalize_intake(payload: Mapping[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables", ["incident"])
    if not isinstance(tables, list) or not tables or any(table not in TABLES for table in tables):
        raise _refuse("tables", f"must be a non-empty list of: {', '.join(TABLES)}")
    excluded = payload.get("excluded_states", list(DEFAULT_EXCLUDED_STATES))
    if not isinstance(excluded, list):
        raise _refuse("excluded_states", "must be a list of state names")
    mapping = payload.get("state_mapping")
    mapping = DEFAULT_STATE_MAPPING if mapping is None else mapping
    if not isinstance(mapping, dict):
        raise _refuse("state_mapping", "must be an object of ServiceNow state to work state")
    normalized_mapping = {}
    for state, target in mapping.items():
        if target not in _WORK_STATES:
            raise _refuse("state_mapping", f"unknown work state for {_state_name(state, 'state_mapping')!r}")
        normalized_mapping[_state_name(state, "state_mapping").lower()] = target
    try:
        query = validate_encoded_query(payload.get("sysparm_query"))
    except InvalidEvidenceRequestError:
        raise _refuse("sysparm_query", "an encoded query may only narrow the listing") from None
    overrides = {}
    for spec in FIELDS:
        try:
            overrides[spec.intake_field] = normalize_entries(payload.get(spec.intake_field), field=spec.intake_field)
        except RecordLimitError as error:
            raise _refuse(spec.intake_field, str(error)) from None
    return {
        "tables": list(dict.fromkeys(tables)),
        "excluded_states": sorted({_state_name(state, "excluded_states") for state in excluded}),
        "sysparm_query": query,
        "state_mapping": normalized_mapping,
        "schedule": _schedule(payload),
        "max_items": _bounded(payload.get("max_items"), DEFAULT_MAX_ITEMS, 1, MAX_MAX_ITEMS, "max_items"),
        **overrides,
    }


def is_closed(state: object, intake: Mapping[str, Any]) -> bool:
    excluded = {str(name).lower() for name in intake.get("excluded_states") or ()}
    return isinstance(state, str) and state.strip().lower() in excluded


def mapped_state(state: object, intake: Mapping[str, Any]) -> tuple[str, str]:
    key = " ".join(state.split()).lower() if isinstance(state, str) else ""
    target = dict(intake.get("state_mapping") or {}).get(key)
    return (target, "configured") if target else ("intake", "unmapped")


__all__ = [
    "DEFAULT_SCHEDULE",
    "DEFAULT_STATE_MAPPING",
    "SOURCE_TYPE",
    "TABLES",
    "is_closed",
    "refused",
    "mapped_state",
    "normalize_intake",
]
