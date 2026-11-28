from __future__ import annotations

import json
import uuid
from typing import Any


def _successful_tool_results(turn_tool_history: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in turn_tool_history:
        if str((item or {}).get("tool_name") or "").strip() != tool_name:
            continue
        result = (item or {}).get("result")
        if isinstance(result, dict) and not result.get("error"):
            results.append(_compact_result(result))
    return results


def _tool_attempted(turn_tool_history: list[dict[str, Any]] | list[Any], tool_names: set[str]) -> bool:
    normalized_names = {str(name or "").strip() for name in tool_names if str(name or "").strip()}
    if not normalized_names:
        return False
    for item in turn_tool_history:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() in normalized_names:
            return True
    return False


def _latest_successful_tool_result(
    turn_tool_history: list[dict[str, Any]] | list[Any], tool_name: str
) -> dict[str, Any]:
    normalized_history = [item for item in turn_tool_history if isinstance(item, dict)]
    results = _successful_tool_results(normalized_history, tool_name)
    return dict(results[-1]) if results else {}


def _build_tool_call(
    tool_name: str, arguments: dict[str, Any], allowed_tool_names: set[str] | None
) -> list[dict[str, Any]]:
    allowed = {str(item).strip() for item in (allowed_tool_names or set()) if str(item).strip()}
    if allowed and tool_name not in allowed:
        return []
    return [
        {
            "id": f"workflow-{uuid.uuid4()}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }
    ]


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    preview = result.get("preview")
    if isinstance(preview, dict):
        compact = preview.get("compact_result")
        if isinstance(compact, dict):
            return compact
    return result


