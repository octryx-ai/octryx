"""The Workspace ``trace_capture`` setting a new Workspace starts with; ``observability.run_capture`` applies it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .observability.run_capture import DEFAULT_MODE

TRACE_CAPTURE_PROJECT_CONFIG_KEY = "trace_capture"


def ensure_default_trace_capture_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    current = dict(config or {})
    trace_capture = current.get(TRACE_CAPTURE_PROJECT_CONFIG_KEY)
    current[TRACE_CAPTURE_PROJECT_CONFIG_KEY] = {
        "mode": DEFAULT_MODE,
        **(dict(trace_capture) if isinstance(trace_capture, Mapping) else {}),
    }
    return current
