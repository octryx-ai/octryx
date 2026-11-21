from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.artifact_store import load_tool_artifact_record, read_tool_artifact_payload
from app.services.tool_artifact.summary import (
    _build_snapshot,
    _top_level_facts,
    _truncate_text,
    build_tool_artifact_envelope,
    build_tool_artifact_summary,
)

from ...models import ToolCall


def _resolve_path_segment(value: Any, path: str) -> Any:
    current = value
    for raw_segment in [segment for segment in str(path or "").split(".") if segment]:
        if isinstance(current, dict):
            if raw_segment not in current:
                raise KeyError(raw_segment)
            current = current[raw_segment]
            continue
        if isinstance(current, list):
            try:
                index = int(raw_segment)
            except ValueError as exc:
                raise KeyError(raw_segment) from exc
            if index < 0 or index >= len(current):
                raise IndexError(index)
            current = current[index]
            continue
        raise KeyError(raw_segment)
    return current


def _excerpt_value(value: Any, *, max_chars: int, max_items: int, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, str):
        return _truncate_text(value, max_chars)
    if isinstance(value, list):
        items = [
            _excerpt_value(item, max_chars=max_chars, max_items=max_items, depth=depth + 1)
            for item in value[:max_items]
        ]
        if len(value) > max_items:
            items.append(f"... ({len(value) - max_items} more items)")
        return items
    if isinstance(value, dict):
        excerpt: dict[str, Any] = {}
        max_keys = max(8, max_items)
        for index, (key, item) in enumerate(value.items()):
            if index >= max_keys:
                excerpt["_truncated_keys"] = len(value) - max_keys
                break
            excerpt[str(key)] = _excerpt_value(item, max_chars=max_chars, max_items=max_items, depth=depth + 1)
        return excerpt
    return value


async def load_tool_artifact_payload(
    db: AsyncSession,
    *,
    session_id: str,
    artifact_id: str,
    detail_level: str = "excerpt",
    max_chars: int = 4000,
    max_items: int = 20,
    path: str | None = None,
) -> dict[str, Any]:
    normalized_artifact_id = str(artifact_id or "").strip()
    if not normalized_artifact_id:
        return {"error": "artifact_id is required"}

    row = (
        await db.execute(
            select(ToolCall).where(
                ToolCall.id == normalized_artifact_id,
                ToolCall.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"error": "Artifact not found in this session"}

    artifact_record = await load_tool_artifact_record(db, artifact_id=row.id)
    if artifact_record is not None:
        payload = read_tool_artifact_payload(artifact_record)
    else:
        payload = row.result if isinstance(row.result, dict) else {"value": row.result}
    selected_path = str(path or "").strip()
    if selected_path:
        try:
            payload = _resolve_path_segment(payload, selected_path)
        except (KeyError, IndexError):
            return {"error": f"path not found: {selected_path}", "artifact_id": row.id, "tool_name": row.tool_name}
    normalized_level = str(detail_level or "excerpt").strip().lower()
    if normalized_level == "summary":
        return _build_snapshot(
            build_tool_artifact_envelope(
                artifact_id=row.id,
                tool_name=row.tool_name,
                payload=payload,
                include_result=False,
                max_facts=max(1, min(max_items, 8)),
            ),
            fact_limit=max(1, min(max_items, 8)),
        )
    if normalized_level == "full":
        rendered = payload
    else:
        rendered = _excerpt_value(
            payload,
            max_chars=max(200, min(int(max_chars or 4000), 12000)),
            max_items=max(1, min(int(max_items or 20), 100)),
        )
        normalized_level = "excerpt"
    return {
        "artifact_id": row.id,
        "tool_name": row.tool_name,
        "detail_level": normalized_level,
        "path": selected_path or None,
        "summary": build_tool_artifact_summary(row.tool_name, payload),
        "salient_facts": _top_level_facts(payload, max_facts=max(1, min(max_items, 8))),
        "result": rendered,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
