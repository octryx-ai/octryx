"""Workspace and file helpers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Message,
    ThreadContext,
    ToolCall,
    TurnTrace,
    User,
)
from ...models import Session as AgentSession
from .workspace_message_page import WorkspaceMessagePageBundle, load_workspace_message_page_bundle

__all__ = [
    "_serialize_session_workspace_changes",
    "_export_session_markdown",
    "_serialize_turn_trace",
    "_load_chat_message_page",
    "_serialize_chat_message_page_bundle",
    "_serialize_thread_context",
]


def _serialize_session_workspace_changes(approvals: list[dict]) -> list[dict]:
    from .approval_serialization import _summarize_change_preview

    changes: list[dict] = []
    for approval in approvals:
        change_preview = approval.get("changePreview") if isinstance(approval, dict) else None
        if not isinstance(change_preview, dict):
            continue
        changes.append(
            {
                "id": change_preview.get("id") or "",
                "approvalId": approval.get("id") or "",
                "toolName": change_preview.get("toolName") or "",
                "requestFingerprint": change_preview.get("requestFingerprint") or "",
                "summary": _summarize_change_preview(change_preview),
                "status": approval.get("status") or "",
                "createdAt": change_preview.get("createdAt") or approval.get("createdAt") or None,
                "preview": change_preview.get("preview") if isinstance(change_preview.get("preview"), dict) else {},
            }
        )
    return sorted(changes, key=lambda item: str(item.get("createdAt") or ""), reverse=True)


def _export_session_markdown(
    *,
    session: AgentSession,
    messages: list[Message],
    tool_calls: list[ToolCall],
) -> str:
    from ...services.session.markdown_export import render_session_markdown_export

    return render_session_markdown_export(session=session, messages=messages, tool_calls=tool_calls)


def _serialize_turn_trace(trace: TurnTrace | None) -> dict | None:
    from .serialization import _serialize_timestamp

    if not trace:
        return None
    return {
        "id": trace.id,
        "provider": trace.provider or "",
        "model": trace.model or "",
        "inputMessages": trace.input_messages_json if isinstance(trace.input_messages_json, list) else [],
        "contextSnapshot": trace.context_snapshot_json if isinstance(trace.context_snapshot_json, dict) else {},
        "toolTrace": trace.tool_trace_json if isinstance(trace.tool_trace_json, list) else [],
        "rawOutput": trace.raw_output if isinstance(trace.raw_output, dict) else {"content": trace.raw_output or ""},
        "usage": trace.usage_json if isinstance(trace.usage_json, dict) else {},
        "createdAt": _serialize_timestamp(trace.created_at),
    }


async def _load_chat_message_page(
    db: AsyncSession,
    *,
    session: AgentSession,
    user: User,
    workspace_root: Path | None,
    selected_runtime_label: str,
    limit: int = 80,
    before_message_id: str | None = None,
) -> tuple[list[dict], bool]:
    from .chat_state import CHAT_MESSAGE_PAGE_SIZE

    normalized_limit = max(1, min(int(limit or CHAT_MESSAGE_PAGE_SIZE), 200))
    page_bundle = await load_workspace_message_page_bundle(
        db,
        session=session,
        user=user,
        limit=normalized_limit,
        before_message_id=before_message_id,
    )
    return _serialize_chat_message_page_bundle(
        page_bundle,
        session=session,
        workspace_root=workspace_root,
        selected_runtime_label=selected_runtime_label,
    )


def _serialize_chat_message_page_bundle(
    page_bundle: WorkspaceMessagePageBundle,
    *,
    session: AgentSession,
    workspace_root: Path | None,
    selected_runtime_label: str,
) -> tuple[list[dict], bool]:
    from ._serialization_ext import _format_message_runtime_label
    from .serialization import _serialize_timestamp
    from .tool_call_serialization import _serialize_tool_call

    feedback_by_message_id = {feedback["message_id"]: feedback for feedback in page_bundle.feedbacks}
    tool_calls_by_message: dict[str, list[ToolCall]] = {}
    for tool_call in page_bundle.tool_calls:
        if tool_call.message_id:
            tool_calls_by_message.setdefault(tool_call.message_id, []).append(tool_call)

    turn_trace_meta_by_message_id: dict[str, dict[str, str]] = {}
    for message_id, trace_id, provider, model in page_bundle.turn_trace_rows:
        if message_id:
            turn_trace_meta_by_message_id[str(message_id)] = {
                "id": str(trace_id), "provider": str(provider or ""), "model": str(model or "")}

    message_rows: list[dict] = []
    for message in page_bundle.messages:
        turn_trace_meta = turn_trace_meta_by_message_id.get(message.id)
        runtime_label = _format_message_runtime_label(
            (turn_trace_meta or {}).get("provider", ""),
            (turn_trace_meta or {}).get("model", "") or message.model,
        )
        if not runtime_label and message.role == "assistant":
            runtime_label = str((session.metadata_ or {}).get("runtime_label") or "").strip() or selected_runtime_label
        elif turn_trace_meta is None and message.role == "assistant":
            session_runtime_label = str((session.metadata_ or {}).get("runtime_label") or "").strip()
            if session_runtime_label and message.model and session_runtime_label.endswith(message.model):
                runtime_label = session_runtime_label
        message_rows.append(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content or "",
                "model": message.model,
                "runtimeLabel": runtime_label,
                "providerName": (turn_trace_meta or {}).get("provider", ""),
                "createdAt": _serialize_timestamp(message.created_at),
                "toolEvents": [
                    _serialize_tool_call(event, workspace_root=workspace_root)
                    for event in tool_calls_by_message.get(message.id, [])
                ],
                "turnTrace": None,
                "turnTraceId": (turn_trace_meta or {}).get("id") or None,
                "feedback": _serialize_feedback(feedback_by_message_id.get(message.id), _serialize_timestamp),
                "origin": message_origin(message),
                "authorId": (author := _author(message, session)),
                "authorName": page_bundle.authors.get(author or "") or None,
            }
        )
    return message_rows, page_bundle.has_more


# A user message older than the recorded author (no author_user_id) is shown under the session's owner.
def _author(message, session: AgentSession) -> str | None:
    return (message.author_user_id or session.user_id) if message.role == "user" else None


WORKFLOW_CONTINUATION_KEY = "workflow_continuation:"
DEVICE_ANSWER_KEY = "device_job:"
# The turn the platform starts on the run's main thread for its own git work (teamwork/device_items.flush).
PLATFORM_GIT_KEY = "teamwork:git:"


def message_origin(message) -> str | None:
    key = getattr(message, "idempotency_key", None) or ""
    if message.role == "user" and key.startswith(WORKFLOW_CONTINUATION_KEY):
        return "workflow"
    if message.role == "user" and key.startswith(PLATFORM_GIT_KEY):
        return "platform"
    if message.role == "assistant" and key.startswith(DEVICE_ANSWER_KEY):
        return "device"
    return None


def _serialize_feedback(entry: dict | None, serialize_timestamp) -> dict | None:
    if entry is None:
        return None
    return {
        "rating": entry["rating"],
        "liked": entry["liked"],
        "disliked": entry["disliked"],
        "aspects": entry["aspects"],
        "createdAt": serialize_timestamp(entry["created_at"]),
        "updatedAt": serialize_timestamp(entry["updated_at"]),
    }


def _serialize_thread_context(thread_context: ThreadContext | None) -> dict | None:
    from .serialization import _serialize_timestamp

    if not thread_context:
        return None
    payload = thread_context.context_json if isinstance(thread_context.context_json, dict) else {}
    return {
        "id": thread_context.id,
        "version": int(thread_context.version or 0),
        "context": payload,
        "derivedFromMessageId": thread_context.derived_from_message_id or "",
        "updatedAt": _serialize_timestamp(thread_context.updated_at),
    }
