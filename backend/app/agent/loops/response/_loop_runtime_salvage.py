"""Runtime-failure salvage: build an answer from what the failed turn itself produced."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.runtime.audit import ToolCall, TurnTrace
from ....services.knowledge_salvage import build_knowledge_salvage_answer
from ....services.prompt_catalog import render_prompt
from ..control._loop_salvage_hooks import render_evidence_salvage_message
from ._loop_runtime_salvage_artifacts import build_artifact_salvage_answer, tool_result_payload

_RUNTIME_SALVAGE_TOOL_LOOKBACK_LIMIT = 96
_NON_FINAL_CONTENT_PATTERN = re.compile(
    r"^\s*(?:i\s+(?:will|would|can|should|need to)|let me|next[, ]|now\s+i|"
    r"i'?ll\s+(?:call|use|check|inspect|build|create)|the next step is)\b",
    re.IGNORECASE,
)


def _usable_runtime_answer_candidate(content: str) -> str:
    text = str(content or "").strip()
    if len(text) < 80:
        return ""
    if _NON_FINAL_CONTENT_PATTERN.search(text):
        return ""
    return text


async def _latest_runtime_answer_candidate(*, db: AsyncSession, session_id: str, turn_started_at: datetime) -> str:
    traces = (
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id == session_id, TurnTrace.created_at >= turn_started_at)
                .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    for trace in traces:
        raw_output = trace.raw_output if isinstance(trace.raw_output, dict) else {}
        candidate = _usable_runtime_answer_candidate(str(raw_output.get("content") or ""))
        if candidate:
            return candidate
    return ""


def _build_diagram_artifact_salvage_message(recent_tool_calls: list[ToolCall]) -> str:
    for tool_call in recent_tool_calls:
        tool_name = str(tool_call.tool_name or "").strip()
        if tool_name not in {"create_diagram", "append_diagram", "edit_diagram"}:
            continue
        result = tool_result_payload(tool_call.result)
        diagram_id = str(result.get("diagram_id") or "").strip()
        title = str(result.get("title") or "").strip()
        if not diagram_id:
            continue
        lines = [
            render_prompt("answer.diagram.complete"),
            "",
            render_prompt("answer.diagram.artifact", artifact_ref=f"diagram://{diagram_id}"),
        ]
        if title:
            lines.extend(["", render_prompt("answer.diagram.title", title=title)])
        lines.extend(["", render_prompt("answer.diagram.created")])
        return "\n".join(lines)
    return ""


async def _turn_tool_calls(
    db: AsyncSession, session_id: str, turn_started_at: datetime, *, successful_only: bool
) -> list[ToolCall]:
    conditions = [ToolCall.session_id == session_id]
    if successful_only:
        conditions.append(ToolCall.status == "success")
    conditions.append(ToolCall.created_at >= turn_started_at)
    return list(
        (
            await db.execute(
                select(ToolCall)
                .where(*conditions)
                .order_by(ToolCall.created_at.desc(), ToolCall.id.desc())
                .limit(_RUNTIME_SALVAGE_TOOL_LOOKBACK_LIMIT)
            )
        )
        .scalars()
        .all()
    )


def _latest_user_request(request_messages: list[dict[str, Any]]) -> str:
    user_request = ""
    for message in reversed(request_messages):
        if isinstance(message, dict) and str(message.get("role") or "").strip() == "user":
            user_request = str(message.get("content") or "").strip()
            if user_request:
                break
    return user_request


async def _evidence_salvage_answer(
    *,
    db: AsyncSession,
    session_id: str,
    turn_started_at: datetime,
    user_request: str,
    recent_tool_calls: list[ToolCall],
    recent_all_tool_calls: list[ToolCall],
) -> str:
    """The first answer the turn's own evidence supports, checked in priority order."""
    diagram_artifact_salvage = _build_diagram_artifact_salvage_message(recent_tool_calls)
    if diagram_artifact_salvage:
        return diagram_artifact_salvage
    evidence_salvage = render_evidence_salvage_message(
        user_request=user_request,
        recent_tool_calls=recent_all_tool_calls,
    )
    if evidence_salvage:
        return evidence_salvage
    runtime_answer = await _latest_runtime_answer_candidate(
        db=db, session_id=session_id, turn_started_at=turn_started_at
    )
    if runtime_answer:
        return runtime_answer
    return build_knowledge_salvage_answer(
        user_request,
        recent_all_tool_calls,
        max_items=10,
        content_chars=900,
    )


async def _build_runtime_error_salvage_message(
    *,
    db: AsyncSession,
    session_id: str,
    request_messages: list[dict[str, Any]],
    turn_started_at: datetime,
) -> str:
    """Build a runtime-failure answer from what *this* turn produced, or ``""``.

    ``turn_started_at`` is the turn boundary (``bound_turn_started_at``): tool
    calls and traces the session persisted before it belong to earlier turns and
    are never read, so a failed turn cannot present an earlier turn's content.
    """
    recent_all_tool_calls = await _turn_tool_calls(db, session_id, turn_started_at, successful_only=False)
    recent_tool_calls = await _turn_tool_calls(db, session_id, turn_started_at, successful_only=True)
    user_request = _latest_user_request(request_messages)
    evidence_answer = await _evidence_salvage_answer(
        db=db,
        session_id=session_id,
        turn_started_at=turn_started_at,
        user_request=user_request,
        recent_tool_calls=recent_tool_calls,
        recent_all_tool_calls=recent_all_tool_calls,
    )
    if evidence_answer:
        return evidence_answer
    return build_artifact_salvage_answer(user_request=user_request, recent_tool_calls=recent_tool_calls)


__all__ = [
    "_build_diagram_artifact_salvage_message",
    "_build_runtime_error_salvage_message",
]
