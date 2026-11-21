"""Elastic-iteration runtime settings helpers."""

from __future__ import annotations

from typing import Any

from app.services.system_config.constants import (
    DEFAULT_ELASTIC_ITERATION_ENABLED,
    DEFAULT_ELASTIC_ITERATION_MAX_BONUS,
    DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD,
)


def _bounded_int(raw_value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def get_elastic_iteration_settings(runtime_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = runtime_settings or {}
    return {
        "enabled": bool(settings.get("elastic_iteration_enabled", DEFAULT_ELASTIC_ITERATION_ENABLED)),
        "max_bonus": _bounded_int(
            settings.get("elastic_iteration_max_bonus"),
            default=DEFAULT_ELASTIC_ITERATION_MAX_BONUS,
            minimum=0,
            maximum=12,
        ),
        "unique_tool_threshold": _bounded_int(
            settings.get("elastic_iteration_unique_tool_threshold"),
            default=DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD,
            minimum=1,
            maximum=6,
        ),
    }


__all__ = ["get_elastic_iteration_settings"]
