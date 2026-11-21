"""Dotted-path reads/writes and ``{field}`` templating over node inputs."""

from __future__ import annotations

import re
from typing import Any

_TEMPLATE_PATTERN = re.compile(r"\{([A-Za-z0-9_.-]+)\}")


def _read_path(value: Any, path: str) -> Any:
    current = value
    for part in [segment for segment in path.replace("$input.", "").split(".") if segment]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _render_template_value(value: Any, input_snapshot: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {str(key): _render_template_value(item, input_snapshot) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_template_value(item, input_snapshot) for item in value]
    if not isinstance(value, str):
        return value
    full_match = _TEMPLATE_PATTERN.fullmatch(value.strip())
    if full_match:
        resolved = _read_path(input_snapshot, full_match.group(1))
        return resolved if resolved is not None else value

    def replace(match: re.Match[str]) -> str:
        resolved = _read_path(input_snapshot, match.group(1))
        return "" if resolved is None else str(resolved)

    return _TEMPLATE_PATTERN.sub(replace, value)


def _write_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [segment for segment in path.split(".") if segment]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value
