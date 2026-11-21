"""Contract helper for the /admin/chat selected-session payload."""

from __future__ import annotations

from typing import Any

from ...models import Project, User
from ...models import Session as AgentSession
from ...services.auth import create_session_stream_token
from ...services.run_capability.chat_write_plan import plan_view
from ...services.session.agent_selection_sources import (
    AGENT_SELECTION_SOURCE_METADATA_KEY,
    closed_agent_selection_source,
)
from ...services.workflow_routing.proposal_decision import workflow_proposal_view
from ._serialization_ext import _session_is_pinned
from .serialization import _serialize_timestamp
from .session_titles import _session_title

__all__ = ["build_selected_chat_session_contract"]


def build_selected_chat_session_contract(
    *,
    selected_session: AgentSession | None,
    selected_row: dict[str, Any] | None,
    selected_project: Project | None,
    selected_status: str,
    selected_run_status: str,
    selected_run_completion_reason: str,
    selected_runtime_target_id: str,
    selected_runtime_label: str,
    selected_agent_id: str,
    selected_agent_name: str,
    selected_stop_reason: str | None,
    selected_task_run_id: str,
    selected_task_status: str,
    selected_task_error: str,
    selected_approvals: list[dict[str, Any]],
    user: User,
    can_grant_standing_confirmation: bool = False,
) -> dict[str, Any] | None:
    """Build the selected-session payload still consumed by /admin/chat."""
    if selected_session is None:
        return None

    metadata = selected_session.metadata_ or {}
    pending_approval_count = sum(1 for approval in selected_approvals if approval.get("status") == "pending")

    return {
        "id": selected_session.id,
        "threadNumber": int(selected_row.get("thread_number") or 0) if selected_row else 0,
        "title": selected_row["title"] if selected_row else _session_title(selected_session, None),
        "status": selected_status,
        "runStatus": selected_run_status,
        "runCompletionReason": selected_run_completion_reason,
        "projectId": selected_session.project_id,
        "projectName": (
            selected_row["project_name"]
            if selected_row
            else (selected_project.name if selected_project else "No project")
        ),
        "isPinned": bool(selected_row.get("is_pinned")) if selected_row else _session_is_pinned(selected_session),
        "runtimeTargetId": selected_runtime_target_id,
        "runtimeLabel": selected_runtime_label,
        "agentId": selected_agent_id,
        "agentName": selected_agent_name,
        "agentType": selected_session.agent_type or "diagnosis",
        "agentSelectionSource": closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY)),
        # The workflow the thread's last turn was sent with (``turn_selection``); "" = standard, also for a
        # thread without a turn yet.
        "workflowKey": str(metadata.get("workflow_key") or "").strip(),
        "workflowProposal": workflow_proposal_view(metadata),
        # A Workspace admin or owner may answer "Always for this Workspace"; the button is hidden
        # for everyone else (the server refuses a grant anyway).
        "canGrantStandingConfirmation": can_grant_standing_confirmation,
        "routingIntent": str(metadata.get("routing_intent") or "").strip() or None,
        "routingReason": str(metadata.get("routing_reason") or "").strip() or None,
        "resumeState": str(metadata.get("resume_state") or "").strip() or None,
        # The request's confirmed write plan while it is active.
        "writePlan": plan_view(metadata),
        "stopReason": selected_stop_reason,
        "startedAt": _serialize_timestamp(selected_session.started_at),
        "taskRunId": selected_task_run_id,
        "taskStatus": selected_task_status,
        "taskError": selected_task_error,
        "approvalCount": len(selected_approvals),
        "pendingApprovalCount": pending_approval_count,
        "streamToken": create_session_stream_token(user_id=user.id, session_id=selected_session.id),
    }
