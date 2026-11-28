"""The ServiceNow connector's record limit: assignment groups and services. Every record is checked client-side,
whatever the server-side query returned."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .servicenow_connector_types import RecordLimitView

GROUPS_FIELD = "servicenow_assignment_groups"
SERVICES_FIELD = "servicenow_services"
MODE_FIELD = "servicenow_filter_mode"
MODE_ALL, MODE_ANY = "all", "any"
MODES = (MODE_ALL, MODE_ANY)
MAX_ENTRIES = 50
MAX_ENTRY_CHARS = 100
_SYS_ID = re.compile(r"^[0-9a-fA-F]{32}$")
# Encoded-query and list separators, control characters and script values can never be part of a name.
_FORBIDDEN = re.compile(r"[\^,\x00-\x1f\x7f]|javascript:", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LimitField:
    key: str
    config_field: str
    intake_field: str
    reference: str
    record_keys: tuple[str, ...]
    label: str

    @property
    def walked(self) -> str:
        return f"{self.reference}.name"


GROUPS = LimitField("assignment_groups", GROUPS_FIELD, "assignment_groups", "assignment_group",
                    ("assignment_group",), "group")
SERVICES = LimitField("services", SERVICES_FIELD, "services", "business_service", ("business_service", "service"),
                      "service")
FIELDS = (GROUPS, SERVICES)
# The record fields a client-side check reads (added to a Table API field list under a limit).
CHECK_FIELDS = tuple(name for spec in FIELDS for name in (spec.reference, spec.walked))


class RecordLimitError(ValueError):
    # The message names the rule, never a value.

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def _name_key(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass(frozen=True, slots=True)
class ValueLimit:
    entries: tuple[str, ...]
    sys_ids: frozenset[str]
    names: frozenset[str]

    def matches(self, sys_id: object = None, name: object = None) -> bool:
        if isinstance(sys_id, str) and sys_id.strip().lower() in self.sys_ids:
            return True
        return isinstance(name, str) and _name_key(name) in self.names


@dataclass(frozen=True, slots=True)
class RecordLimit:
    groups: ValueLimit | None = None
    services: ValueLimit | None = None
    mode: str = MODE_ALL

    def of(self, spec: LimitField) -> ValueLimit | None:
        return self.groups if spec is GROUPS else self.services

    def lists(self) -> list[tuple[LimitField, ValueLimit]]:
        return [(spec, values) for spec, values in ((GROUPS, self.groups), (SERVICES, self.services))
                if values is not None]

    def combine(self, results: list[bool]) -> bool:
        if not results:
            return False
        return any(results) if self.mode == MODE_ANY else all(results)

    def matches(self, refs: Mapping[str, tuple[object, object]]) -> bool:
        # A missing field never matches.
        return self.combine([values.matches(*refs.get(spec.key, (None, None))) for spec, values in self.lists()])


_NOTHING_VALUES = ValueLimit(entries=("<invalid record limit>",), sys_ids=frozenset(), names=frozenset())
NOTHING = RecordLimit(groups=_NOTHING_VALUES)


def normalize_entries(value: Any, *, field: str = GROUPS_FIELD) -> list[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        raise RecordLimitError(f"{field} must be a list of at most {MAX_ENTRIES} names or sys_ids")
    entries: dict[str, str] = {}
    for raw in value:
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > MAX_ENTRY_CHARS:
            raise RecordLimitError(f"{field} entries must be non-empty texts of at most {MAX_ENTRY_CHARS} characters")
        text = " ".join(raw.split())
        if _FORBIDDEN.search(text):
            raise RecordLimitError(f"{field} entries must not contain '^', ',', control characters or scripts")
        entries.setdefault(text.casefold(), text.lower() if _SYS_ID.match(text) else text)
    return list(entries.values())


def normalize_mode(value: Any) -> str:
    if value is None or value == "":
        return MODE_ALL
    if value not in MODES:
        raise RecordLimitError(f"{MODE_FIELD} must be one of: {', '.join(MODES)}")
    return value


def _values_of(entries: list[str]) -> ValueLimit | None:
    if not entries:
        return None
    ids = frozenset(entry.lower() for entry in entries if _SYS_ID.match(entry))
    names = frozenset(_name_key(entry) for entry in entries if not _SYS_ID.match(entry))
    return ValueLimit(entries=tuple(entries), sys_ids=ids, names=names)


def _limit_of(groups: list[str], services: list[str], mode: str) -> RecordLimit | None:
    if not groups and not services:
        return None
    return RecordLimit(groups=_values_of(groups), services=_values_of(services), mode=mode)


def record_limit(config: Mapping[str, Any]) -> RecordLimit | None:
    # An invalid stored value matches nothing.
    try:
        return _limit_of(normalize_entries(config.get(GROUPS_FIELD), field=GROUPS_FIELD),
                         normalize_entries(config.get(SERVICES_FIELD), field=SERVICES_FIELD),
                         normalize_mode(config.get(MODE_FIELD)))
    except RecordLimitError:
        return NOTHING


def narrowed(config: Mapping[str, Any], overrides: Mapping[str, list[str]]) -> RecordLimit | None:
    # An override must lie within the connector's list; an extra OR-ed list would widen the limit.
    connector = record_limit(config)
    if connector is NOTHING:
        return NOTHING
    mode = connector.mode if connector is not None else normalize_mode(config.get(MODE_FIELD))
    lists: dict[str, list[str]] = {}
    for spec in FIELDS:
        current = connector.of(spec) if connector is not None else None
        override = list(overrides.get(spec.intake_field) or [])
        if override and current is not None:
            allowed = {entry.casefold() for entry in current.entries}
            if any(entry.casefold() not in allowed for entry in override):
                raise RecordLimitError(f"the intake's {spec.intake_field} may only narrow the connector's list",
                                       field=spec.intake_field)
        elif override and connector is not None and mode == MODE_ANY:
            raise RecordLimitError(f"the intake's {spec.intake_field} would widen the connector's 'any' limit",
                                   field=spec.intake_field)
        lists[spec.key] = override or (list(current.entries) if current is not None else [])
    return _limit_of(lists["assignment_groups"], lists["services"], mode)


def _reference(value: Any) -> tuple[Any, Any]:
    if isinstance(value, Mapping):
        return value.get("value"), value.get("display_value", value.get("name"))
    if isinstance(value, str):
        return value, value
    return None, None


def _walked(record: Mapping[str, Any], spec: LimitField) -> Any:
    walked = record.get(spec.walked)
    return walked.get("display_value", walked.get("value")) if isinstance(walked, Mapping) else walked


def record_refs(record: Mapping[str, Any]) -> dict[str, list[tuple[Any, Any]]]:
    refs: dict[str, list[tuple[Any, Any]]] = {}
    for spec in FIELDS:
        found = [_reference(record.get(key)) for key in spec.record_keys if record.get(key) not in (None, "")]
        if (walked := _walked(record, spec)) not in (None, ""):
            found.append((None, walked))
        refs[spec.key] = found
    return refs


def record_in_limit(record: Mapping[str, Any], limit: RecordLimit | None) -> bool:
    # Never passes without a limited field.
    if limit is None:
        return True
    refs = record_refs(record)
    return limit.combine([any(values.matches(*ref) for ref in refs[spec.key]) for spec, values in limit.lists()])


def collapse(record: Mapping[str, Any], display: str) -> dict[str, Any]:
    if display == "all":
        return dict(record)
    key = "display_value" if display == "true" else "value"
    return {name: (value.get(key) if isinstance(value, Mapping) and key in value else value)
            for name, value in record.items()}


def describe(limit: RecordLimit | None) -> RecordLimitView:
    if limit is None:
        return {"assignment_groups": [], "services": [], "filter_mode": MODE_ALL}
    return {"assignment_groups": list(limit.groups.entries) if limit.groups else [],
            "services": list(limit.services.entries) if limit.services else [], "filter_mode": limit.mode}


__all__ = [
    "CHECK_FIELDS",
    "FIELDS",
    "GROUPS",
    "GROUPS_FIELD",
    "MODES",
    "MODE_FIELD",
    "NOTHING",
    "SERVICES",
    "SERVICES_FIELD",
    "LimitField",
    "RecordLimit",
    "RecordLimitError",
    "ValueLimit",
    "collapse",
    "describe",
    "narrowed",
    "normalize_entries",
    "normalize_mode",
    "record_in_limit",
    "record_limit",
    "record_refs",
]
