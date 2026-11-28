"""The Work source registry: ``source_type`` -> its :class:`~.protocol.WorkIntakeSource`."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

GENERIC_SYNC_TASK_TYPE = "secure_work_work_intake_sync"
CODE_UNKNOWN_SOURCE = "intake_source_unknown"


@dataclass(frozen=True, slots=True)
class SourceEntry:
    source_type: str
    label: str
    task_type: str
    module: str  # ``package.module:ATTRIBUTE`` of the implementation


_ENTRIES: dict[str, SourceEntry] = {}
_LOADED: dict[str, Any] = {}


def register(entry: SourceEntry) -> None:
    _ENTRIES[entry.source_type] = entry
    _LOADED.pop(entry.source_type, None)


register(SourceEntry("jira", "Jira", "secure_work_jira_sync",
                     "app.services.secure_work.jira.intake_source:SOURCE"))
register(SourceEntry("servicenow", "ServiceNow", "secure_work_servicenow_sync",
                     "app.services.secure_work.servicenow.intake_source:SOURCE"))
register(SourceEntry("custom_rest", "Custom REST", GENERIC_SYNC_TASK_TYPE,
                     "app.services.secure_work.custom_rest.intake_source:SOURCE"))


def source_types() -> tuple[str, ...]:
    return tuple(_ENTRIES)


def entry_of(source_type: object) -> SourceEntry | None:
    return _ENTRIES.get(str(source_type or "").strip().lower())


def source_for(source_type: object) -> Any | None:
    entry = entry_of(source_type)
    if entry is None:
        return None
    if entry.source_type not in _LOADED:
        module, _, attribute = entry.module.partition(":")
        _LOADED[entry.source_type] = getattr(importlib.import_module(module), attribute)
    return _LOADED[entry.source_type]


def require_source(source_type: object, *, field: str = "source_type") -> Any:
    source = source_for(source_type)
    if source is None:
        raise HTTPException(status_code=422, detail={
            "state": "invalid_request", "code": CODE_UNKNOWN_SOURCE, "field": field,
            "message": f"{field} must be one of: {', '.join(source_types())}"})
    return source


def sync_task_types() -> frozenset[str]:
    return frozenset({GENERIC_SYNC_TASK_TYPE, *(entry.task_type for entry in _ENTRIES.values())})


def entry_for_task_type(task_type: object) -> SourceEntry | None:
    return next((entry for entry in _ENTRIES.values()
                 if entry.task_type == task_type and entry.task_type != GENERIC_SYNC_TASK_TYPE), None)


__all__ = [
    "CODE_UNKNOWN_SOURCE",
    "GENERIC_SYNC_TASK_TYPE",
    "SourceEntry",
    "entry_for_task_type",
    "entry_of",
    "register",
    "require_source",
    "source_for",
    "source_types",
    "sync_task_types",
]
