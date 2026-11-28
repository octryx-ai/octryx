"""Selected-session loader for the chat state builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, ThreadContext, ToolCall, User
from ...models import Session as AgentSession
from ...services.change_preview import list_change_previews_by_approval_id, serialize_change_preview
from ...services.session.workspace import resolve_session_workspace_root
from .approval_serialization import _serialize_approval, approver_names
from .serialization import (
    _collect_session_tree_ids,
    _effective_session_run_completion_reason,
    _effective_session_run_status,
    _effective_session_status_for_chat,
    _session_stop_reason,
)
from .thread_usage_stats import _load_thread_usage_stats
from .tool_call_serialization import _serialize_tool_call
from .workspace import _serialize_chat_message_page_bundle
from .workspace_message_page import load_workspace_message_page_bundle

__all__ = ["SelectedChatSessionState", "_load_selected_chat_session_state"]


@dataclass(slots=True)
class SelectedChatSessionState:
    status: str
    stop_reason: str | None
    task_error: str
    task_run_id: str
    task_status: str
    run_status: str
    run_completion_reason: str
    messages: list[dict] = field(default_factory=list)
    messages_has_more: bool = False
    right_panel_events: list[dict] = field(default_factory=list)
    thread_stats: dict[str, Any] | None = None
    thread_context: ThreadContext | None = None
    approvals: list[dict] = field(default_factory=list)
    workspace_root: Path | None = None


async def _load_selected_chat_session_state(
    db: AsyncSession,
    *,
    user: User,
    selected_session: AgentSession,
    selected_runtime_label: str,
    task_run_map: dict[str, Any],
    latest_task_run_by_session_id: dict[str, Any],
    top_level_active_rows: list[dict],
    chat_message_page_size: int,
) -> SelectedChatSessionState:
    # Refresh metadata to pick up writes from concurrent background tasks (e.g. a
    # chat-turn background task (services/session/turn_runner) may have updated run_status just now).
    await db.refresh(selected_session, attribute_names=["metadata_"])
    workspace_root = await resolve_session_workspace_root(db, selected_session, create=False)
    selected_task_run = latest_task_run_by_session_id.get(selected_session.id) or task_run_map.get(
        str((selected_session.metadata_ or {}).get("task_run_id") or "").strip()
    )
    status = _effective_session_status_for_chat(selected_session, selected_task_run)
    stop_reason = _session_stop_reason(selected_session)
    task_error = selected_task_run.error if selected_task_run and selected_task_run.error else ""
    task_run_id = selected_task_run.id if selected_task_run else ""
    task_status = selected_task_run.status if selected_task_run and selected_task_run.status else ""

    message_page_bundle = await load_workspace_message_page_bundle(
        db,
        session=selected_session,
        user=user,
        limit=max(1, min(int(chat_message_page_size or 80), 200)),
    )
    thread_context = (
        await db.execute(select(ThreadContext).where(ThreadContext.session_id == selected_session.id))
    ).scalar_one_or_none()
    selected_approval_models = (
        (
            await db.execute(
                select(Approval).where(Approval.session_id == selected_session.id).order_by(Approval.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    selected_preview_by_approval_id = await list_change_previews_by_approval_id(
        db,
        [approval.id for approval in selected_approval_models],
    )
    approver_name_by_id = await approver_names(db, list(selected_approval_models))
    approvals = [
        _serialize_approval(
            approval,
            change_preview=serialize_change_preview(selected_preview_by_approval_id.get(approval.id)),
            approver_name_by_id=approver_name_by_id,
        )
        for approval in selected_approval_models
    ]
    last_assistant_message = next(
        (message for message in reversed(message_page_bundle.messages) if message.role == "assistant" and message.content),
        None,
    )
    run_status = _effective_session_run_status(
        selected_session,
        task_run=selected_task_run,
        fallback_content=(last_assistant_message.content if last_assistant_message else None),
    )
    run_completion_reason = _effective_session_run_completion_reason(
        selected_session,
        task_run=selected_task_run,
        fallback_content=(last_assistant_message.content if last_assistant_message else None),
    )

    selected_session_rows_by_id = {row["id"]: row for row in top_level_active_rows}
    for row in top_level_active_rows:
        for child in row.get("sub_threads") or []:
            selected_session_rows_by_id[child["id"]] = child
    usage_session_ids = _collect_session_tree_ids(selected_session.id, selected_session_rows_by_id)
    if not usage_session_ids:
        usage_session_ids = [selected_session.id]

    messages, messages_has_more = _serialize_chat_message_page_bundle(
        message_page_bundle,
        session=selected_session,
        workspace_root=workspace_root,
        selected_runtime_label=selected_runtime_label,
    )
    thread_stats = await _load_thread_usage_stats(db, session_ids=usage_session_ids)
    if not thread_stats.get("last_model") and message_page_bundle.messages:
        thread_stats["last_model"] = message_page_bundle.messages[-1].model or ""

    latest_tool_calls = (
        (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.session_id == selected_session.id)
                .order_by(ToolCall.created_at.desc(), ToolCall.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    right_panel_events = [
        _serialize_tool_call(tool_call, workspace_root=workspace_root) for tool_call in reversed(latest_tool_calls)
    ]

    return SelectedChatSessionState(
        status=status,
        stop_reason=stop_reason,
        task_error=task_error,
        task_run_id=task_run_id,
        task_status=task_status,
        run_status=run_status,
        run_completion_reason=run_completion_reason,
        messages=messages,
        messages_has_more=messages_has_more,
        right_panel_events=right_panel_events,
        thread_stats=thread_stats,
        thread_context=thread_context,
        approvals=approvals,
        workspace_root=workspace_root,
    )
