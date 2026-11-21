"""Shared limits and value helpers of the external activity linking (``external_activity``)."""

from __future__ import annotations

from typing import Any

MAX_CANDIDATE_ITEMS = 500
MAX_EXTERNAL_ACTIVITY = 50
TERMINAL_WORK_STATES = {"done", "completed", "cancelled", "canceled", "rejected", "superseded"}
EVENT_REVIEW_STATES = {"needs_replan", "needs_human_review", "needs_remediation"}


def _string_list(value: Any) -> list[str]:
    return [_string(item) for item in _list(value) if _string(item)]


def _string_set(value: Any) -> set[str]:
    return {_string(item) for item in _list(value) if _string(item)}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: current for key, current in value.items() if current not in (None, "", [], {})}
