"""The chat state a client gets right after it starts or continues a turn: the selected thread only."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...models import Message, Project, User
from ...models import Session as AgentSession
from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY, list_agent_modes, serialize_agent_mode
from ...services.auth import create_session_stream_token
from ...services.run_capability.chat_write_plan import plan_view
from ...services.session.agent_selection_sources import (
    AGENT_SELECTION_SOURCE_METADATA_KEY,
    closed_agent_selection_source,
)
from ...services.session.chat_agent_guidance import CHAT_AGENT_GUIDANCE_KEY, project_chat_agent_guidance
from ...services.session.run_state import get_session_run_completion_reason, get_session_run_status
from ...services.session.session_title import TITLE_SOURCE_KEY
from ...services.session.workspace import resolve_session_workspace_root
from ...services.standing_approvals.permission import can_grant_standing_approval
from ...services.workflow_routing.proposal_decision import workflow_proposal_view
from ...services.workspace_composition import get_workspace_execution_view
from ._chat_launch_surface import build_chat_launch_surface
from ._routing_catalog import _list_chat_agent_catalog
from ._serialization_ext import _session_is_pinned
from .chat_state import _load_branding_config
from .serialization import _serialize_timestamp, _session_stop_reason
from .session_titles import _session_title
from .workspace import _load_chat_message_page

__all__ = ["_build_chat_turn_ack_state"]


async def _ack_runtime_selection(
    db: AsyncSession,
    session: AgentSession,
    metadata: dict,
    runtime_target_id: str,
) -> tuple[str, list[dict], str]:
    from app.services.runtime_options import list_chat_runtime_options

    workspace_execution_view = (
        await get_workspace_execution_view(db, workspace_id=session.project_id) if session.project_id else None
    )
    resolved_runtime_target_id = str(metadata.get("runtime_target_id") or runtime_target_id or "").strip()
    runtime_options = await list_chat_runtime_options(
        db,
        workspace_execution_view=workspace_execution_view,
        include_runtime_target_id=resolved_runtime_target_id,
    )
    runtime_label_by_id = {option["value"]: option["label"] for option in runtime_options}
    selected_runtime_label = runtime_label_by_id.get(
        resolved_runtime_target_id,
        str(metadata.get("runtime_label") or "").strip() or runtime_label_by_id.get("", "Automatic fallback chain"),
    )
    return resolved_runtime_target_id, runtime_options, selected_runtime_label


async def _first_user_message(db: AsyncSession, session: AgentSession) -> Message | None:
    return (
        await db.execute(
            select(Message)
            .where(Message.session_id == session.id, Message.role == "user", Message.content.is_not(None))
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _user_role_names(db: AsyncSession, user: User) -> list[str]:
    from ...models import Role, UserRole

    _role_result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    )
    return [r[0] for r in _role_result.all()]


def _ack_selected_session(
    *,
    user: User,
    session: AgentSession,
    metadata: dict,
    first_user_message: Message | None,
    selected_project: Project | None,
    runtime: tuple[str, list[dict], str],
    selected_agent_id: str,
    selected_agent_name: str,
    agent_type: str,
    can_grant: bool,
) -> dict:
    resolved_runtime_target_id, _runtime_options, selected_runtime_label = runtime
    return {
        "id": session.id,
        "threadNumber": 0,
        "title": _session_title(session, first_user_message),
        "titleSource": str((session.metadata_ or {}).get(TITLE_SOURCE_KEY) or "") or None,
        "status": _effective_session_status(session),
        "runStatus": get_session_run_status(session),
        "runCompletionReason": get_session_run_completion_reason(session),
        "projectId": session.project_id,
        "projectName": selected_project.name if selected_project else "No project",
        "isPinned": _session_is_pinned(session),
        "runtimeTargetId": resolved_runtime_target_id,
        "runtimeLabel": selected_runtime_label,
        "agentId": selected_agent_id,
        "agentName": selected_agent_name,
        "agentType": session.agent_type or agent_type or DEFAULT_AGENT_MODE_KEY,
        "agentSelectionSource": closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY)),
        "workflowKey": (str(metadata["workflow_key"] or "").strip() if "workflow_key" in metadata else None),
        "workflowProposal": workflow_proposal_view(metadata),
        "canGrantStandingConfirmation": can_grant,
        "routingIntent": str(metadata.get("routing_intent") or "").strip() or None,
        "routingReason": str(metadata.get("routing_reason") or "").strip() or None,
        "resumeState": str(metadata.get("resume_state") or "").strip() or None,
        # The request's confirmed write plan while it is active.
        "writePlan": plan_view(metadata),
        "stopReason": _session_stop_reason(session),
        "startedAt": _serialize_timestamp(session.started_at),
        "taskRunId": "",
        "taskStatus": "",
        "taskError": "",
        "approvalCount": 0,
        "pendingApprovalCount": 0,
        "streamToken": create_session_stream_token(user_id=user.id, session_id=session.id),
    }


def _ack_composer_state(
    *,
    session: AgentSession,
    metadata: dict,
    selected_project: Project | None,
    runtime: tuple[str, list[dict], str],
    thinking_level: str,
    selected_agent_id: str,
    selected_agent_name: str,
    agent_type: str,
) -> dict:
    resolved_runtime_target_id, runtime_options, selected_runtime_label = runtime
    return {
        "selectedProject": ({"id": selected_project.id, "name": selected_project.name} if selected_project else None),
        "selectedProjectId": session.project_id or "",
        "runtimeOptions": runtime_options,
        "selectedRuntimeTargetId": resolved_runtime_target_id,
        "selectedRuntimeLabel": selected_runtime_label,
        "selectedThinkingLevel": str(metadata.get("thinking_level") or thinking_level or "light").strip() or "light",
        "selectedAgentId": selected_agent_id,
        "selectedAgentName": selected_agent_name,
        "selectedAgentType": session.agent_type or agent_type or DEFAULT_AGENT_MODE_KEY,
        "selectedAgentSelectionSource": (
            closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY)) or ""
        ),
    }


def _selected_agent_name(agent_guidance: dict, selected_agent_id: str) -> str:
    latest_turn_agent = agent_guidance["lastTurnAgent"] or {}
    return (latest_turn_agent.get("name") or "") if latest_turn_agent.get("id") == selected_agent_id else ""


def _ack_head(user: User, user_roles: list[str], serialized_projects: list[dict]) -> dict:
    return {
        "currentUser": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "displayName": user.display_name or "",
            "roles": user_roles,
        },
        "launchSurface": build_chat_launch_surface(user_roles=user_roles, project_options=serialized_projects),
        "branding": _load_branding_config(),
        # Not included in an acknowledgement (null): the client keeps its list; [] would mean "no chats".
        "activeThreadGroups": None,
        "archivedThreadCount": None,
        "archivedThreads": None,
    }


def _ack_empty_panels() -> dict:
    return {
        "traceEvents": [],
        "traceEventCount": 0,
        "selectedThreadStats": None,
        "selectedThreadContext": None,
        "selectedApprovals": [],
        "newThread": False,
        "settingsUrl": "/admin/settings",
        "toolsUrl": "/admin/tools",
        "controlPlaneUrl": "/chat?area=admin&tab=providers",
        "dashboardUrl": "/chat",
    }


async def _build_chat_turn_ack_state(
    request,
    db: AsyncSession,
    *,
    user: User,
    session: AgentSession,
    runtime_target_id: str,
    thinking_level: str,
    agent_id: str,
    agent_type: str,
) -> dict:
    metadata = dict(session.metadata_ or {})
    runtime = await _ack_runtime_selection(db, session, metadata, runtime_target_id)
    selected_project = await db.get(Project, session.project_id) if session.project_id else None
    selected_agent_id = str(metadata.get("agent_definition_id") or agent_id or "").strip()
    # One owner-scoped projection with the bootstrap: the current name, never a persisted foreign one.
    agent_guidance = await project_chat_agent_guidance(db, user_id=user.id, session=session)
    selected_agent_name = _selected_agent_name(agent_guidance, selected_agent_id)
    selected_workspace_root = await resolve_session_workspace_root(db, session, create=False)
    selected_messages, selected_messages_has_more = await _load_chat_message_page(
        db,
        session=session,
        user=user,
        workspace_root=selected_workspace_root,
        selected_runtime_label=runtime[2],
    )
    first_user_message = await _first_user_message(db, session)
    user_roles = await _user_role_names(db, user)
    can_grant = await can_grant_standing_approval(db, user_id=user.id, project_id=session.project_id)
    agent_options, agent_groups = await _list_chat_agent_catalog(db, user=user, project_id=session.project_id)
    serialized_projects = [{"id": selected_project.id, "name": selected_project.name}] if selected_project else []
    selected = {
        "session": session,
        "metadata": metadata,
        "selected_project": selected_project,
        "runtime": runtime,
        "selected_agent_id": selected_agent_id,
        "selected_agent_name": selected_agent_name,
        "agent_type": agent_type,
    }
    return {
        **_ack_head(user, user_roles, serialized_projects),
        "selectedSession": _ack_selected_session(
            user=user, first_user_message=first_user_message, can_grant=can_grant, **selected
        ),
        "selectedSessionIsArchived": False,
        "selectedSessionIsRunning": True,
        "selectedMessages": selected_messages,
        "selectedMessagesHasMore": selected_messages_has_more,
        **_ack_composer_state(thinking_level=thinking_level, **selected),
        "agentModes": [serialize_agent_mode(mode) for mode in list_agent_modes()],
        "projects": serialized_projects,
        **_ack_empty_panels(),
        "agentOptions": agent_options,
        "agentGroups": agent_groups,
        CHAT_AGENT_GUIDANCE_KEY: agent_guidance,
    }
