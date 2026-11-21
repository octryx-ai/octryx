"""The effective Workspace (project) scope of a chat turn.

One resolution, shared by the chat turn preparation and the workflow proposal that runs before
the preparation lock (``workflow_routing/proposal_prefetch.py``), so both see the same scope:
the requested project, else the session's project, else the only
project assigned to the user (global admins may run without one).
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import User
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE, get_project_role_for_user
from ..workspace_composition import get_workspace_execution_view, normalize_workspace_execution_view
from .collaboration import require_session_access
from .turn_preparation import resolve_required_project_scope
from .turn_refusals import TurnRefusalState, TurnRefusedError
from .turn_request import SESSION_SCOPE_EXISTING


async def load_turn_session(db: AsyncSession, *, user_id: str, session_id: str) -> AgentSession | None:
    """The user's own session for ``session_id``; ``None`` for a new session or another user's id."""
    if not session_id:
        return None
    stmt = select(AgentSession).where(AgentSession.id == session_id, AgentSession.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def load_writable_turn_session(db: AsyncSession, *, user_id: str, session_id: str) -> AgentSession:
    """The existing session ``user_id`` may write to (owner, contributor, team member, write grant).

    ``/api/v1`` names an existing session. The chat-session access rule answers; its 404 and
    403 become ``session_not_found`` and ``session_access_denied``.
    """
    try:
        session, _role = await require_session_access(db, session_id=session_id, user_id=user_id, require_write=True)
    except HTTPException as refused:
        state = (
            TurnRefusalState.SESSION_ACCESS_DENIED if refused.status_code == 403 else TurnRefusalState.SESSION_NOT_FOUND
        )
        raise TurnRefusedError(state, str(refused.detail)) from None
    return session


async def load_request_turn_session(
    db: AsyncSession, *, user_id: str, session_id: str, session_scope: str
) -> AgentSession | None:
    """The session a turn request names, under the request's own scope rule.

    ``/api/v1`` (``SESSION_SCOPE_EXISTING``) needs an existing writable session; ``/chat/api`` uses
    the caller's own session or a new one. Preparation and the admission before the workflow
    proposal both load through here, so neither can see a different session.
    """
    if session_scope == SESSION_SCOPE_EXISTING:
        return await load_writable_turn_session(db, user_id=user_id, session_id=session_id)
    return await load_turn_session(db, user_id=user_id, session_id=session_id)


async def resolve_turn_project_scope(
    db: AsyncSession,
    *,
    user: User,
    project_id: str,
    session: AgentSession | None,
) -> tuple[str, str]:
    """``(project_id, effective_project_id)`` of the turn; scope conflicts raise ``TurnRefusedError``."""
    project_id = await resolve_required_project_scope(db, user=user, project_id=project_id, session=session)
    effective_project_id = str(project_id or (session.project_id if session and session.project_id else "")).strip()
    return project_id, effective_project_id


async def require_project_member(db: AsyncSession, *, user_id: str, project_id: str) -> None:
    if project_id and await get_project_role_for_user(db, user_id, project_id) is None:
        # The same refusal as an unknown Workspace: an outsider never learns whether a Workspace exists.
        raise TurnRefusedError(TurnRefusalState.PROJECT_NOT_FOUND, WORKSPACE_NOT_FOUND_MESSAGE)


async def turn_workspace_execution_view(
    db: AsyncSession, *, user_id: str, session: AgentSession | None, effective_project_id: str
) -> dict | None:
    """The session's recorded view, else the Workspace's; the caller must be a project member."""
    raw = (session.metadata_ or {}).get("workspace_execution_view") if session else None
    view = normalize_workspace_execution_view(dict(raw or {})) if session else None
    await require_project_member(db, user_id=user_id, project_id=effective_project_id)
    if view is None and effective_project_id:
        view = normalize_workspace_execution_view(
            await get_workspace_execution_view(db, workspace_id=effective_project_id)
        )
    return view


__all__ = [
    "load_request_turn_session",
    "load_turn_session",
    "load_writable_turn_session",
    "require_project_member",
    "resolve_turn_project_scope",
    "turn_workspace_execution_view",
]
