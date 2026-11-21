from __future__ import annotations

import json
from typing import Any


def safe_json_value(
    value: str | None, fallback: Any, expected_type: type[Any] | tuple[type[Any], ...] | None = None
) -> Any:
    try:
        payload = json.loads(value or "null")
    except (json.JSONDecodeError, TypeError):
        return fallback
    if expected_type is not None and not isinstance(payload, expected_type):
        return fallback
    return payload


def safe_json_dict(value: str | None) -> dict[str, Any]:
    return safe_json_value(value, {}, dict)


def safe_json_list(value: str | None) -> list[Any]:
    return safe_json_value(value, [], list)


def safe_string_list(value: str | None) -> list[str]:
    return [str(item).strip() for item in safe_json_list(value) if str(item).strip()]


def dump_string_list(value: list[str] | tuple[str, ...] | None) -> str:
    return json.dumps([str(item).strip() for item in (value or []) if str(item).strip()])


def dump_json_dict(value: dict[str, Any] | None) -> str:
    payload = value if isinstance(value, dict) else {}
    return json.dumps(payload)


def dump_json_list(value: list[Any] | tuple[Any, ...] | None) -> str:
    payload = list(value or [])
    return json.dumps(payload)
