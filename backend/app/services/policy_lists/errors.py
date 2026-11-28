"""Closed refusal codes of an admin edit to a governed policy list (W22b)."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException

INVALID_PAYLOAD = "invalid_payload"
INVALID_ENTRY = "invalid_entry"
DUPLICATE_ENTRY = "duplicate_entry"
EMPTY_LIST = "empty_list"
UNKNOWN_TOOL = "unknown_tool"
REQUIRED_TOOL_MISSING = "required_tool_missing"
UNKNOWN_CAPABILITY = "unknown_capability"
CAPABILITY_IN_USE = "capability_in_use"
DIAGRAM_TYPE_NOT_RENDERABLE = "diagram_type_not_renderable"
OUT_OF_RANGE = "out_of_range"
VERSION_CONFLICT = "version_conflict"
UNKNOWN_POLICY_LIST = "unknown_policy_list"

POLICY_LIST_ERROR_CODES = frozenset(
    {
        INVALID_PAYLOAD,
        INVALID_ENTRY,
        DUPLICATE_ENTRY,
        EMPTY_LIST,
        UNKNOWN_TOOL,
        REQUIRED_TOOL_MISSING,
        UNKNOWN_CAPABILITY,
        CAPABILITY_IN_USE,
        DIAGRAM_TYPE_NOT_RENDERABLE,
        OUT_OF_RANGE,
        VERSION_CONFLICT,
        UNKNOWN_POLICY_LIST,
    }
)

_STATUS_BY_CODE = {UNKNOWN_POLICY_LIST: 404, VERSION_CONFLICT: 409}


class PolicyListError(ValueError):
    def __init__(self, code: str, message: str, values: Iterable[str] = ()) -> None:
        if code not in POLICY_LIST_ERROR_CODES:
            raise ValueError(f"unknown policy list error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.values = sorted({str(value) for value in values})

    @property
    def status_code(self) -> int:
        return _STATUS_BY_CODE.get(self.code, 422)

    def detail(self) -> dict[str, object]:
        return {"code": self.code, "values": self.values, "message": self.message}


def as_http_exception(error: PolicyListError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail())


def refuse_duplicates(values: Iterable[str], *, what: str) -> None:
    seen: set[str] = set()
    duplicates = {value for value in values if value in seen or seen.add(value)}
    if duplicates:
        raise PolicyListError(DUPLICATE_ENTRY, f"{what} names an entry more than once.", duplicates)


__all__ = [
    "CAPABILITY_IN_USE",
    "DIAGRAM_TYPE_NOT_RENDERABLE",
    "DUPLICATE_ENTRY",
    "EMPTY_LIST",
    "INVALID_ENTRY",
    "INVALID_PAYLOAD",
    "OUT_OF_RANGE",
    "POLICY_LIST_ERROR_CODES",
    "PolicyListError",
    "REQUIRED_TOOL_MISSING",
    "UNKNOWN_CAPABILITY",
    "UNKNOWN_POLICY_LIST",
    "UNKNOWN_TOOL",
    "VERSION_CONFLICT",
    "as_http_exception",
    "refuse_duplicates",
]
