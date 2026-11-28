"""The selected-session part of a chat payload, shared by the bootstrap and the selected-session view. One builder, so a
switch through the view returns exactly the bootstrap's fields."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...models import Project, User
from ...models import Session as AgentSession
from ...services.session.chat_agent_guidance import CHAT_AGENT_GUIDANCE_KEY, project_chat_agent_guidance
from ...services.standing_approvals.permission import can_grant_standing_approval
from ...services.workflow_runs.pr_links import session_pull_requests
from ._chat_runtime_selection import ChatRuntimeSelection
from ._chat_selected_session_contract import build_selected_chat_session_contract
from ._chat_state_selected_session import SelectedChatSessionState, _load_selected_chat_session_state
from ._chat_state_selection import build_chat_selection_state
from ._serialization_ext import _serialize_thread_stats
from .workspace import _serialize_thread_context

__all__ = ["SELECTED_VIEW_KEYS", "build_selected_view_fields"]

# The keys this module owns in the bootstrap payload (and the whole selected-session view payload).
SELECTED_VIEW_KEYS = (
    "requestedSessionNotFound",
    "selectedSession",
    "selectedSessionIsArchived",
    "selectedSessionIsRunning",
    "selectedMessages",
    "selectedMessagesHasMore",
    "selectedProject",
    "selectedProjectId",
    "runtimeOptions",
    "selectedRuntimeTargetId",
    "selectedRuntimeLabel",
    "selectedThinkingLevel",
    "selectedAgentId",
    "selectedAgentName",
    "selectedAgentType",
    "selectedAgentSelectionSource",
    "traceEvents",
    "traceEventCount",
    "selectedThreadStats",
    "selectedThreadContext",
    "selectedApprovals",
    "selectedSessionPullRequests",
    "selectedWorkspace",
    CHAT_AGENT_GUIDANCE_KEY,
)


async def build_selected_view_fields(
    db: AsyncSession,
    *,
    user: User,
    selected_session: AgentSession | None,
    selected_row: dict[str, Any] | None,
    selection: ChatRuntimeSelection,
    requested_session_missing: bool,
    task_run_map: dict[str, Any],
    latest_task_run_by_session_id: dict[str, Any],
    top_level_active_rows: list[dict[str, Any]],
    requested_agent_id: str,
    chat_message_page_size: int,
) -> dict[str, Any]:
    selected_project_id = selection.selected_project_id
    selected_project = await db.get(Project, selected_project_id) if selected_project_id else None
    state = (
        await _load_selected_chat_session_state(
            db,
            user=user,
            selected_session=selected_session,
            selected_runtime_label=selection.selected_runtime_label,
            task_run_map=task_run_map,
            latest_task_run_by_session_id=latest_task_run_by_session_id,
            top_level_active_rows=top_level_active_rows,
            chat_message_page_size=chat_message_page_size,
        )
        if selected_session
        else SelectedChatSessionState(status="", stop_reason=None, task_error="", task_run_id="", task_status="",
                                      run_status="", run_completion_reason="")
    )
    selection_state = build_chat_selection_state(
        selected_session_metadata=(selected_session.metadata_ or {}) if selected_session else None,
        selected_session_exists=bool(selected_session),
        selected_agent_id=selection.selected_agent_id,
        selected_agent=selection.selected_agent,
        selected_agent_type=selection.selected_agent_type,
        selected_agent_type_explicit=selection.selected_agent_type_explicit,
        default_selection={},
    )
    effective_status = _effective_session_status(selected_session) if selected_session else ""
    return {
        "requestedSessionNotFound": requested_session_missing,
        "selectedSession": build_selected_chat_session_contract(
            selected_session=selected_session,
            selected_row=selected_row,
            selected_project=selected_project,
            selected_status=state.status,
            selected_run_status=state.run_status,
            selected_run_completion_reason=state.run_completion_reason,
            selected_runtime_target_id=selection.selected_runtime_target_id,
            selected_runtime_label=selection.selected_runtime_label,
            selected_agent_id=selection.selected_agent_id,
            selected_agent_name=selection.selected_agent.name if selection.selected_agent else "",
            selected_stop_reason=state.stop_reason,
            selected_task_run_id=state.task_run_id,
            selected_task_status=state.task_status,
            selected_task_error=state.task_error,
            selected_approvals=state.approvals,
            user=user,
            can_grant_standing_confirmation=await can_grant_standing_approval(
                db, user_id=user.id, project_id=selected_session.project_id if selected_session else None
            ),
        ),
        "selectedSessionIsArchived": effective_status == "archived",
        "selectedSessionIsRunning": effective_status in {"running", "awaiting_subagents"},
        "selectedMessages": state.messages,
        "selectedMessagesHasMore": state.messages_has_more,
        "selectedProject": ({"id": selected_project.id, "name": selected_project.name} if selected_project else None),
        "selectedProjectId": selected_project_id,
        "runtimeOptions": selection.runtime_options,
        "selectedRuntimeTargetId": selection.selected_runtime_target_id,
        "selectedRuntimeLabel": selection.selected_runtime_label,
        "selectedThinkingLevel": selection.selected_thinking_level,
        "selectedAgentId": selection_state.selected_agent_id,
        "selectedAgentName": selection_state.selected_agent_name,
        "selectedAgentType": selection_state.selected_agent_type,
        "selectedAgentSelectionSource": selection_state.selected_agent_selection_source,
        "traceEvents": state.right_panel_events,
        "traceEventCount": len(state.right_panel_events),
        "selectedThreadStats": _serialize_thread_stats(state.thread_stats),
        "selectedThreadContext": _serialize_thread_context(state.thread_context),
        "selectedApprovals": state.approvals,
        "selectedSessionPullRequests": await session_pull_requests(db, selected_session.id) if selected_session else [],
        "selectedWorkspace": None,
        CHAT_AGENT_GUIDANCE_KEY: await project_chat_agent_guidance(
            db, user_id=user.id, session=selected_session, requested_agent_id=requested_agent_id
        ),
    }
