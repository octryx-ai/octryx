from __future__ import annotations

import json
import uuid
from typing import Any


def merge_tool_history_from_messages(
    turn_tool_history: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return workflow tool history enriched from persisted tool messages."""
    combined = [item for item in (turn_tool_history or []) if isinstance(item, dict)]
    known_artifact_ids = {
        str(item.get("artifact_id") or "").strip()
        for item in combined
        if str(item.get("artifact_id") or "").strip()
    }
    for item in _tool_history_items_from_messages(messages or []):
        artifact_id = str(item.get("artifact_id") or "").strip()
        if artifact_id and artifact_id in known_artifact_ids:
            continue
        if artifact_id:
            known_artifact_ids.add(artifact_id)
        combined.append(item)
    return combined


def _tool_history_items_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or str(message.get("role") or "").strip() != "tool":
            continue
        payload = _tool_payload_from_message(message)
        tool_name = str(payload.get("tool_name") or "").strip()
        if not tool_name:
            continue
        result = _result_from_tool_payload(payload)
        if not isinstance(result, dict):
            continue
        items.append(
            {
                "artifact_id": str(payload.get("artifact_id") or "").strip(),
                "tool_name": tool_name,
                "tool_call_id": str(payload.get("tool_call_id") or "").strip(),
                "params": {},
                "result": result,
            }
        )
    return items


def _tool_payload_from_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _result_from_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict):
        return _compact_result(result)
    compact_result = payload.get("compact_result")
    if isinstance(compact_result, dict):
        return compact_result
    preview = payload.get("preview")
    if isinstance(preview, dict):
        preview_compact = preview.get("compact_result")
        if isinstance(preview_compact, dict):
            return preview_compact
    return {}


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


