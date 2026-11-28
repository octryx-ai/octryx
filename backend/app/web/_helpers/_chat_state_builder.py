"""Builder for the main chat state payload."""

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session.turn_tasks import effective_session_status as _effective_session_status

from ...models import Project, Role, User
from ...models import (
    Session as AgentSession,
)
from ...models import (
    UserRole as _UserRole,
)
from ...services.access_control import workspace_visible
from ...services.agent_mode import list_agent_modes, serialize_agent_mode
from ...services.project.default_workspace import default_workspace_id
from ...services.project.new_chat_workspace import new_chat_workspace
from ._chat_launch_surface import build_chat_launch_surface
from ._chat_runtime_selection import AUTOMATIC_RUNTIME_LABEL, resolve_chat_runtime_selection
from ._chat_selected_view_fields import build_selected_view_fields
from ._routing_catalog import _list_chat_agent_catalog
from ._serialization_ext import _serialize_thread_row
from .chat_thread_pages import (
    CHAT_THREAD_GROUP_PAGE_SIZE,
    count_chat_thread_groups,
    list_visible_chat_projects,
    load_descendant_sessions,
    load_initial_chat_thread_pages,
    serialize_active_thread_groups,
)
from .chat_thread_row_facts import session_last_activity
from .chat_thread_rows import build_chat_thread_rows
from .chat_thread_scope import count_archived_threads
from .chat_thread_visibility import with_thread_visibility_memo
from .serialization import _resolve_root_session, _sort_datetime_value

__all__ = ["_build_chat_state", "_list_accessible_chat_projects"]

# Duplicated constant to avoid importing from chat_state.py (would create a circular import).
# The authoritative definition remains in chat_state.py; both must stay in sync.
_CHAT_MESSAGE_PAGE_SIZE = 80


async def _list_accessible_chat_projects(db: AsyncSession, *, user: User) -> list[Project]:
    return await list_visible_chat_projects(db, user=user)


@dataclass(frozen=True, kw_only=True)
class _ChatThreads:
    selected_session: AgentSession | None
    requested_session_missing: bool
    row_payload: Any
    active_chat_groups: list
    top_level_active_rows: list
    archived_session_rows: list


async def _load_sorted_thread_sessions(
    db: AsyncSession, *, user: User, selected_session: AgentSession | None
) -> tuple[list[AgentSession], dict[str, int]]:
    selected_root_session = await _resolve_root_session(db, selected_session)
    group_counts_by_project_id = await count_chat_thread_groups(db, user=user)
    top_level_sessions = await load_initial_chat_thread_pages(
        db,
        user=user,
        group_counts_by_project_id=group_counts_by_project_id,
        page_size=CHAT_THREAD_GROUP_PAGE_SIZE,
    )
    top_level_session_ids = {session.id for session in top_level_sessions}
    if selected_root_session and selected_root_session.id not in top_level_session_ids:
        top_level_sessions.append(selected_root_session)
        top_level_session_ids.add(selected_root_session.id)
    if selected_root_session and str(_effective_session_status(selected_root_session) or "").strip().lower() != "archived":
        selected_group_id = str(selected_root_session.project_id or "")
        group_counts_by_project_id[selected_group_id] = max(1, group_counts_by_project_id.get(selected_group_id, 0))

    descendant_sessions = await load_descendant_sessions(db, user=user, top_level_session_ids=top_level_session_ids)

    sessions_by_id = {session.id: session for session in [*top_level_sessions, *descendant_sessions]}
    if selected_session and selected_session.id not in sessions_by_id:
        sessions_by_id[selected_session.id] = selected_session
    sessions = sorted(
        sessions_by_id.values(),
        key=lambda session: _sort_datetime_value(session_last_activity(session)),
        reverse=True,
    )
    return sessions, group_counts_by_project_id


async def _load_chat_threads(
    db: AsyncSession, *, user: User, session_id: str | None, new_thread: bool
) -> _ChatThreads:
    selected_session = None
    if session_id and not new_thread:
        selected_session = (
            await db.execute(select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user.id))
        ).scalar_one_or_none()
    # A requested thread that does not exist or is not the user's is reported, never swapped for another thread.
    requested_session_missing = bool(session_id and not new_thread and selected_session is None)
    sessions, group_counts_by_project_id = await _load_sorted_thread_sessions(
        db, user=user, selected_session=selected_session
    )
    if not selected_session and sessions and not new_thread and not requested_session_missing:
        selected_session = sessions[0]

    row_payload = await build_chat_thread_rows(
        db,
        sessions=sessions,
        selected_session=selected_session,
        automatic_runtime_label=AUTOMATIC_RUNTIME_LABEL,
    )
    active_session_rows = []
    archived_session_rows = []
    for row in row_payload.rows:
        if str(row.get("status") or "").strip().lower() == "archived":
            archived_session_rows.append(row)
        else:
            active_session_rows.append(row)

    active_chat_groups, top_level_active_rows = serialize_active_thread_groups(
        active_session_rows=active_session_rows,
        archived_session_rows=archived_session_rows,
        group_counts_by_project_id=group_counts_by_project_id,
        page_size=CHAT_THREAD_GROUP_PAGE_SIZE,
    )
    return _ChatThreads(
        selected_session=selected_session,
        requested_session_missing=requested_session_missing,
        row_payload=row_payload,
        active_chat_groups=active_chat_groups,
        top_level_active_rows=top_level_active_rows,
        archived_session_rows=archived_session_rows,
    )


async def _resolve_chat_selection(
    db: AsyncSession,
    *,
    user: User,
    projects: list[Project],
    selected_session: AgentSession | None,
    new_thread: bool,
    project_id: str,
    runtime_target_id: str,
    agent_id: str,
    agent_type: str,
):
    if project_id and not await workspace_visible(db, user.id, project_id):
        # An unknown Workspace and one the person is no member of are not selected: the chat opens as without one,
        # and nothing of a foreign Workspace (its runtimes, agents, archive state) shapes the answer.
        project_id = ""
    if new_thread and project_id:
        # A new chat never starts in an archived Workspace (e.g. the one of the latest thread, which "New chat"
        # passes on): the default Workspace, else the person's only one, else none.
        project_id = await new_chat_workspace(
            db, user=user, project_id=project_id, active_workspace_ids=[project.id for project in projects]
        )
    selection = await resolve_chat_runtime_selection(
        db,
        user=user,
        selected_session=selected_session,
        new_thread=new_thread,
        project_id=project_id,
        runtime_target_id=runtime_target_id,
        agent_id=agent_id,
        agent_type=agent_type,
    )
    # The person's own private Workspace is their default; the Instance default only without one.
    own_private = next((project for project in projects if project.access_mode == "private"
                        and str(project.owner_user_id) == str(user.id)), None)
    default_project_id = own_private.id if own_private is not None else await default_workspace_id(db)
    return selection, own_private, default_project_id


async def _user_role_names(db: AsyncSession, user: User) -> list[str]:
    _role_result = await db.execute(
        select(Role.name).join(_UserRole, _UserRole.role_id == Role.id).where(_UserRole.user_id == user.id)
    )
    return [r[0] for r in _role_result.all()]


async def _chat_state_payload(
    db: AsyncSession,
    *,
    user: User,
    projects: list[Project],
    threads: _ChatThreads,
    chat_project_id: str | None,
    own_private: Project | None,
    default_project_id: str | None,
    new_thread: bool,
    selected_fields: dict,
) -> dict:
    from .chat_state import _load_branding_config

    user_roles = await _user_role_names(db, user)
    agent_modes = [serialize_agent_mode(mode) for mode in list_agent_modes()]
    agent_options, agent_groups = await _list_chat_agent_catalog(db, user=user, project_id=chat_project_id)
    serialized_projects = [
        {"id": project.id, "name": "Private" if project is own_private else project.name,
         "isDefault": project.id == default_project_id, "private": project is own_private}
        for project in projects
    ]
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
        "activeThreadGroups": threads.active_chat_groups,
        "archivedThreadCount": await count_archived_threads(db, user=user),
        "archivedThreads": [_serialize_thread_row(row) for row in threads.archived_session_rows],
        "agentModes": agent_modes,
        "projects": serialized_projects,
        "new_thread": new_thread,
        "newThread": new_thread,
        "settingsUrl": "/admin/settings",
        "toolsUrl": "/admin/tools",
        "controlPlaneUrl": "/chat?area=admin&tab=providers",
        "dashboardUrl": "/chat",
        "agentOptions": agent_options,
        "agentGroups": agent_groups,
        **selected_fields,
    }


@with_thread_visibility_memo
async def _build_chat_state(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    session_id: str | None = None,
    project_id: str = "",
    runtime_target_id: str = "",
    agent_id: str = "",
    agent_type: str = "",
    new_thread: bool = False,
) -> dict:
    from .chat_state import CHAT_MESSAGE_PAGE_SIZE

    projects = await list_visible_chat_projects(db, user=user)
    threads = await _load_chat_threads(db, user=user, session_id=session_id, new_thread=new_thread)
    selected_session = threads.selected_session
    selection, own_private, default_project_id = await _resolve_chat_selection(
        db,
        user=user,
        projects=projects,
        selected_session=selected_session,
        new_thread=new_thread,
        project_id=project_id,
        runtime_target_id=runtime_target_id,
        agent_id=agent_id,
        agent_type=agent_type,
    )
    selected_fields = await build_selected_view_fields(
        db,
        user=user,
        selected_session=selected_session,
        selected_row=threads.row_payload.selected_row,
        selection=selection,
        requested_session_missing=threads.requested_session_missing,
        task_run_map=threads.row_payload.task_run_map,
        latest_task_run_by_session_id=threads.row_payload.latest_task_run_by_session_id,
        top_level_active_rows=threads.top_level_active_rows,
        requested_agent_id=agent_id,
        chat_message_page_size=CHAT_MESSAGE_PAGE_SIZE,
    )
    chat_project_id = str(selection.selected_project_id or "").strip() or (
        selected_session.project_id if selected_session and selected_session.project_id else None
    )
    return await _chat_state_payload(
        db,
        user=user,
        projects=projects,
        threads=threads,
        chat_project_id=chat_project_id,
        own_private=own_private,
        default_project_id=default_project_id,
        new_thread=new_thread,
        selected_fields=selected_fields,
    )
