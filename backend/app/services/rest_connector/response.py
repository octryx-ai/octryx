"""Shaping a JSON answer: locate the records, drop those outside the caller's scope, keep the selected fields.

There is no artificial cut: every record in scope is returned, and a large
answer goes through the platform's tool-result compaction and tool artifacts like any other tool result.
"""

from __future__ import annotations

from typing import Any

#: Keys under which list APIs commonly return their records, tried when the operation names no records path.
_COMMON_RECORD_KEYS = ("items", "results", "result", "data", "records", "values", "value", "entries", "rows")
_MISSING = object()


class ScopeFilterError(ValueError):
    """A result filter is set but the answer has no records it can check; fail closed rather than pass data."""


def get_path(value: Any, path: str) -> Any:
    """The value at a dotted path; a key that itself contains dots matches whole (longest first).

    OData v4 names its next page ``@odata.nextLink`` (one key), so
    ``@odata.nextLink`` must not be read as ``["@odata"]["nextLink"]``."""
    parts = [part for part in str(path or "").split(".") if part]
    node, index = value, 0
    while index < len(parts):
        if not isinstance(node, dict):
            return _MISSING
        for end in range(len(parts), index, -1):
            key = ".".join(parts[index:end])
            if key in node:
                node, index = node[key], end
                break
        else:
            return _MISSING
    return node


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = target
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def locate_records(body: Any, records_path: str | None) -> tuple[list[Any] | None, str | None]:
    """``(records, path)``: the list the answer carries, and where (``""`` for a top-level list)."""
    if records_path:
        found = get_path(body, records_path)
        return (found, records_path) if isinstance(found, list) else (None, None)
    if isinstance(body, list):
        return body, ""
    if isinstance(body, dict):
        for key in _COMMON_RECORD_KEYS:
            if isinstance(body.get(key), list):
                return body[key], key
    return None, None


def _replace_records(body: Any, path: str, records: list[Any]) -> Any:
    if path == "":
        return records
    copied = dict(body)
    node = copied
    parts = path.split(".")
    for part in parts[:-1]:
        node[part] = dict(node[part])
        node = node[part]
    node[parts[-1]] = records
    return copied


def _matches(record: Any, field: str, expected: Any) -> bool:
    actual = get_path(record, field)
    if actual is _MISSING:
        return False
    return actual == expected or str(actual) == str(expected)


def _select(record: Any, paths: list[str]) -> Any:
    if not isinstance(record, dict) or not paths:
        return record
    selected: dict[str, Any] = {}
    for path in paths:
        value = get_path(record, path)
        if value is not _MISSING:
            _set_path(selected, path, value)
    return selected


def shape_body(
    body: Any,
    *,
    records_path: str | None,
    result_filter: dict[str, Any] | None,
    response_select: list[str],
) -> tuple[Any, int, int]:
    """``(shaped body, records kept, records dropped)``; refuses (``ScopeFilterError``) a filter it cannot apply."""
    records, path = locate_records(body, records_path)
    if records is None:
        if isinstance(body, dict) and result_filter is not None:
            # One object (a single record): it is in scope or it is not returned at all.
            if not _matches(body, result_filter["field"], result_filter["value"]):
                return None, 0, 1
            return _select(body, response_select), 1, 0
        if result_filter is not None:
            raise ScopeFilterError("The answer has no records the scope filter can check.")
        return _select(body, response_select), (1 if body not in (None, "") else 0), 0
    kept = records
    dropped = 0
    if result_filter is not None:
        kept = [record for record in records if _matches(record, result_filter["field"], result_filter["value"])]
        dropped = len(records) - len(kept)
    kept = [_select(record, response_select) for record in kept]
    return _replace_records(body, path or "", kept), len(kept), dropped


__all__ = ["ScopeFilterError", "get_path", "locate_records", "shape_body"]
