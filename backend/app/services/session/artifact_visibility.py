"""Session-scoped trace and diagram artifact visibility helpers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import ToolCall, TurnTrace
from ..artifact_store import load_tool_artifact_record, read_tool_artifact_payload

DIAGRAM_TOOL_NAMES = frozenset({"create_diagram", "edit_diagram", "append_diagram"})


async def load_user_turn_trace(
    db: AsyncSession,
    *,
    user_id: str,
    trace_id: str,
) -> TurnTrace | None:
    return (
        await db.execute(
            select(TurnTrace)
            .join(AgentSession, AgentSession.id == TurnTrace.session_id)
            .where(
                TurnTrace.id == trace_id,
                AgentSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def resolve_user_diagram_artifact(
    db: AsyncSession,
    *,
    user_id: str,
    path: str,
) -> dict:
    raw_path = str(path or "").strip()
    if raw_path.startswith("artifact://"):
        tool_call_id = raw_path.removeprefix("artifact://").strip()
        tool_call = (
            await db.execute(
                select(ToolCall)
                .join(AgentSession, AgentSession.id == ToolCall.session_id)
                .where(ToolCall.id == tool_call_id, AgentSession.user_id == user_id)
            )
        ).scalar_one_or_none()
        if tool_call is None or str(tool_call.tool_name or "") not in DIAGRAM_TOOL_NAMES:
            raise HTTPException(status_code=404, detail="Diagram artifact not found")
        return _diagram_effective_payload(await _load_tool_call_payload(db, tool_call))

    if not raw_path.startswith("diagram://"):
        raise HTTPException(status_code=400, detail="Unsupported diagram artifact path")

    diagram_id = raw_path.removeprefix("diagram://").strip()
    if not diagram_id:
        raise HTTPException(status_code=400, detail="Diagram id is required")
    candidates = (
        await db.execute(
            select(ToolCall)
            .join(AgentSession, AgentSession.id == ToolCall.session_id)
            .where(ToolCall.tool_name.in_(sorted(DIAGRAM_TOOL_NAMES)), AgentSession.user_id == user_id)
            .order_by(ToolCall.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    for tool_call in candidates:
        payload = _diagram_effective_payload(await _load_tool_call_payload(db, tool_call))
        if str(payload.get("diagram_id") or "").strip() == diagram_id:
            return payload
    raise HTTPException(status_code=404, detail="Diagram artifact not found")


async def _load_tool_call_payload(db: AsyncSession, tool_call: ToolCall) -> dict:
    artifact_record = await load_tool_artifact_record(db, artifact_id=str(tool_call.id))
    if artifact_record is not None:
        payload = read_tool_artifact_payload(artifact_record)
        return payload if isinstance(payload, dict) else {}
    return tool_call.result if isinstance(tool_call.result, dict) else {}


def _diagram_effective_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else {}
    compact_result = preview.get("compact_result") if isinstance(preview.get("compact_result"), dict) else None
    return compact_result or payload


__all__ = [
    "DIAGRAM_TOOL_NAMES",
    "load_user_turn_trace",
    "resolve_user_diagram_artifact",
]
