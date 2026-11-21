"""Normalization helpers for connector policy payloads."""

from __future__ import annotations

from typing import Any


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_connector_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(raw_policy or {})
    return {
        "tool_instructions": str(policy.get("tool_instructions") or "").strip(),
        "extra_tools": _normalize_string_list(policy.get("extra_tools")),
        "disabled_tools": _normalize_string_list(policy.get("disabled_tools")),
    }
