from __future__ import annotations

from typing import Any

from ..jira_values import blank_to_none, list_value, string_list


def identity_token(value: Any) -> str:
    if isinstance(value, dict):
        raw = (
            value.get("username")
            or value.get("name")
            or value.get("display_name")
            or value.get("email")
            or value.get("id")
        )
    else:
        raw = value
    return str(raw or "").strip()


def object_or_string_list(value: Any) -> list[Any]:
    values = list_value(value)
    if not values and isinstance(value, str):
        values = string_list(value)
    normalized: list[Any] = []
    for entry in values:
        if isinstance(entry, dict):
            normalized.append(dict(entry))
        elif text := blank_to_none(entry):
            normalized.append({"name": text})
    return normalized


def mismatch(
    mismatch_type: str,
    message: str,
    severity: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": mismatch_type,
        "severity": severity,
        "message": message,
        "details": details or {},
    }
