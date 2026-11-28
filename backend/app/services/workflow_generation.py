"""Generate reviewable workflow drafts from existing session evidence. Validated before it is stored, published only by
a second admin."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, ToolCall, TurnTrace, User
from ..models import Session as AgentSession
from .flow_definitions import create_flow_definition
from .workflow_generation_graph import (
    MAX_SOURCE_TOOL_CALLS,
    MAX_SOURCE_TRACES,
    build_flow_definition,
    first_user_message,
    phase_tools,
    slug,
)

MAX_SOURCE_MESSAGES = 12


async def _session_evidence(
    db: AsyncSession, session_id: str
) -> tuple[list[Message], list[ToolCall], list[TurnTrace]]:
    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc(), Message.id.asc())
                .limit(MAX_SOURCE_MESSAGES)
            )
        )
        .scalars()
        .all()
    )
    tool_calls = (
        (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.session_id == session_id)
                .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
                .limit(MAX_SOURCE_TOOL_CALLS)
            )
        )
        .scalars()
        .all()
    )
    traces = (
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id == session_id)
                .order_by(TurnTrace.created_at.asc(), TurnTrace.id.asc())
                .limit(MAX_SOURCE_TRACES)
            )
        )
        .scalars()
        .all()
    )
    return messages, tool_calls, traces


def _publish_metadata(
    *,
    session_id: str,
    source_evidence: dict[str, Any],
    review_summary: dict[str, Any],
    traces: list[TurnTrace],
    allowed_tools: list[str],
) -> dict[str, Any]:
    return {
        "generated": True,
        "source": "generate-workflow",
        "source_session_id": session_id,
        "source_evidence": source_evidence,
        "review_summary": review_summary,
        "risks": _risks(traces=traces, allowed_tools=allowed_tools),
        "validation_recommendations": _validation_recommendations(allowed_tools),
    }


async def generate_workflow_draft_from_session(
    db: AsyncSession,
    *,
    session_id: str,
    current_user: User,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = await db.get(AgentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages, tool_calls, traces = await _session_evidence(db, session_id)
    if not messages and not tool_calls and not traces:
        raise HTTPException(status_code=422, detail="Session has no evidence for workflow generation")

    title = _draft_title(messages, payload or {})
    allowed_tools = _unique_tool_names(tool_calls)
    definition = build_flow_definition(
        session=session,
        title=title,
        messages=messages,
        tool_calls=tool_calls,
        traces=traces,
        allowed_tools=allowed_tools,
    )
    source_evidence = _source_evidence(messages=messages, tool_calls=tool_calls, traces=traces)
    review_summary = _review_summary(title=title, allowed_tools=allowed_tools, source_evidence=source_evidence)
    flow = await create_flow_definition(
        db,
        current_user=current_user,
        payload={
            "key": await _unique_flow_key(db, title=title, session_id=session_id),
            "name": title,
            "description": f"Generated workflow draft from session {session_id}.",
            "project_id": session.project_id,
            "definition": definition,
            "publish_metadata": _publish_metadata(
                session_id=session_id, source_evidence=source_evidence, review_summary=review_summary,
                traces=traces, allowed_tools=allowed_tools,
            ),
            "runtime_settings": {},
            "policy_bindings": {
                "safety_class": "review_required",
                "requires_human_publish": True,
            },
        },
    )
    return {
        "status": "draft_created",
        "flow": flow,
        "review_summary": review_summary,
        "source_evidence": source_evidence,
    }


def _source_evidence(
    *,
    messages: list[Message],
    tool_calls: list[ToolCall],
    traces: list[TurnTrace],
) -> dict[str, Any]:
    return {
        "message_ids": [message.id for message in messages],
        "tool_call_ids": [call.id for call in tool_calls],
        "trace_ids": [trace.id for trace in traces],
        "tool_names": _unique_tool_names(tool_calls),
        "assistant_outputs": [
            {"message_id": message.id, "preview": str(message.content or "")[:240]}
            for message in messages
            if message.role == "assistant"
        ][:4],
    }


def _review_summary(*, title: str, allowed_tools: list[str], source_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": title,
        "summary": "Generated draft from session history, tool calls and turn traces.",
        "allowed_tools": allowed_tools,
        "source_counts": {
            "messages": len(source_evidence["message_ids"]),
            "tool_calls": len(source_evidence["tool_call_ids"]),
            "traces": len(source_evidence["trace_ids"]),
        },
        "review_status": "needs_human_review",
    }


def _risks(*, traces: list[TurnTrace], allowed_tools: list[str]) -> list[str]:
    risks = ["Generated step order must be reviewed against current governance and tool policy."]
    if not phase_tools(allowed_tools):
        risks.append("No successful tool evidence was available; draft contains an investigation placeholder.")
    dropped = [tool for tool in allowed_tools if tool not in phase_tools(allowed_tools)]
    if dropped:
        risks.append("Tools that deliver outside the workspace (or are unknown) are not offered: "
                     f"{', '.join(dropped)}.")
    if not traces:
        risks.append("No turn traces were available; prompt-frame provenance is incomplete.")
    return risks


def _validation_recommendations(allowed_tools: list[str]) -> list[str]:
    recommendations = [
        "Review the generated steps in the workflow designer before publishing.",
        "Run Flow Definition validation and a workflow quality gate fixture.",
    ]
    if allowed_tools:
        recommendations.append("Confirm every allowed tool is still permitted for the target project/runtime.")
    return recommendations


async def _unique_flow_key(db: AsyncSession, *, title: str, session_id: str) -> str:
    from ..models import FlowDefinition

    base = f"generated-{slug(title)}-{session_id[:8]}"[:150].strip("-") or f"generated-{session_id[:8]}"
    key = base
    suffix = 2
    while (
        await db.execute(select(FlowDefinition.id).where(FlowDefinition.key == key))
    ).scalar_one_or_none() is not None:
        key = f"{base}-{suffix}"
        suffix += 1
    return key


def _draft_title(messages: list[Message], payload: dict[str, Any]) -> str:
    requested = str(payload.get("name") or payload.get("title") or "").strip()
    if requested:
        return requested[:120]
    first_user = first_user_message(messages)
    if first_user:
        return f"Generated workflow: {first_user[:80]}"
    return "Generated workflow draft"



def _unique_tool_names(tool_calls: list[ToolCall]) -> list[str]:
    names = [str(call.tool_name or "").strip() for call in tool_calls]
    return list(dict.fromkeys(name for name in names if name))

