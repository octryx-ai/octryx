"""The ServiceNow connector's closed config values, its record-limit view and the answer of a Scripted REST listing
tool."""

from typing import Any, Literal, TypedDict

ApiStyle = Literal["table", "scripted"]
WorknoteMode = Literal["off", "scripted_post", "table_api"]
FilterMode = Literal["all", "any"]


class RecordLimitView(TypedDict):
    assignment_groups: list[str]
    services: list[str]
    filter_mode: FilterMode


class ScriptedIncidents(TypedDict):
    count: int
    total: int | None  # None when the listing was limited client-side or the endpoint sent no total
    api_style: Literal["scripted"]
    incidents: list[dict[str, Any]]  # normalized records: display values flattened, ``table`` and ``url`` added


class ScriptedChanges(TypedDict):
    count: int
    total: int | None
    api_style: Literal["scripted"]
    changes: list[dict[str, Any]]


class ScriptedError(TypedDict):
    error: str
    code: str


ScriptedListing = ScriptedIncidents | ScriptedChanges | ScriptedError

__all__ = [
    "ApiStyle",
    "FilterMode",
    "RecordLimitView",
    "ScriptedChanges",
    "ScriptedError",
    "ScriptedIncidents",
    "ScriptedListing",
    "WorknoteMode",
]
