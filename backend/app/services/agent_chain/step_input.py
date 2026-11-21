"""How a chain step's prompt is rendered from the chain context, and what its output adds to it."""

from __future__ import annotations

import json
from typing import Any


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        try:
            return value.format_map(_SafeFormatDict(context))
        except Exception:
            return value
    if isinstance(value, dict):
        return {str(key): _render_value(sub_value, context) for key, sub_value in value.items()}
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    return value


def _format_step_input(step: dict[str, Any], context: dict[str, Any]) -> str:
    input_mapping = step.get("input_mapping")
    if input_mapping is None:
        base = context.get("initial_input")
        if isinstance(base, str):
            return base
        return json.dumps(base or {}, ensure_ascii=True, sort_keys=True)
    rendered = _render_value(input_mapping, context)
    if isinstance(rendered, str):
        return rendered
    if isinstance(rendered, dict) and isinstance(rendered.get("template"), str):
        return str(rendered["template"])
    return json.dumps(rendered, ensure_ascii=True, sort_keys=True)


def _extract_step_output(step: dict[str, Any], step_result: dict[str, Any]) -> tuple[str | None, Any]:
    mapping = dict(step.get("output_mapping") or {})
    key = str(mapping.get("key") or "").strip() or None
    if not key:
        return None, None
    source = str(mapping.get("source") or "content").strip().lower()
    if source == "result":
        return key, step_result
    if source == "session_id":
        return key, step_result.get("session_id")
    return key, step_result.get("content")
