"""Binds the request's data viewer to the route's principal; a platform admin cannot tell a private Workspace from an
unknown id."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute, APIWebSocketRoute
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Project, Session, User
from ...services.access_control import workspace_not_found
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth.service import get_current_user
from ...services.data_access import bind_request_viewer
from ...services.project.private_workspace import is_private, private_role
from ...services.session.collaboration import get_session_access_role
from ...services.session.resource_access import SESSION_NOT_FOUND_DETAIL
from ...services.session.turn_refusals import TurnRefusal, TurnRefusalState
from .cookie_principal import load_active_principal
from .route_principal import RoutePrincipal, route_principal

PATH_KEYS = ("project_id", "workspace_id", "projectId", "workspaceId")
QUERY_KEYS = ("project_id", "workspace_id")
SESSION_KEYS = ("session_id", "sessionId")
# They look a session up among the caller's own only, so any other id already answers as a missing thread.
OWN_SESSION_ROUTES = frozenset({f"{mount}/chat/api/{path}" for mount in ("", "/admin")
                                for path in ("bootstrap", "sessions/{session_id}/view")})
# The HTML shell never looks the session up; the page then reads the bootstrap, an own-session route.
CHAT_SHELL_ROUTES = frozenset({"/chat", "/admin/chat"})
# The turn route answers a missing session with its typed refusal; every other session route with the plain detail.
TURN_ROUTE = ("POST", "/api/v1/sessions/{session_id}/messages")
# They read only the shared session itself and enforce its share role (``require_session_access``).
SESSION_CONTENT_ROUTES = frozenset({("GET", f"/api/v1/sessions/{{session_id}}{suffix}")
                                    for suffix in ("", "/messages", "/export.pdf", "/export.analysis.json")}
                                   | {("GET", "/api/v1/canvas/sessions/{session_id}")})


def _named(request: Request, path_keys: tuple[str, ...], query_keys: tuple[str, ...]) -> set[str]:
    path = request.path_params or {}
    named = {str(path.get(key) or "").strip() for key in path_keys}
    named |= {str(request.query_params.get(key) or "").strip() for key in query_keys}
    return {value[:64] for value in named if value}


def _hidden(project: Project | None, user_id: str) -> bool:
    return project is None or (is_private(project) and private_role(project, user_id) is None)


async def _refused_session(db: AsyncSession, user_id: str, sessions: set[str], share_opens: bool) -> bool:
    for session_id in sessions:
        session = await db.get(Session, session_id)
        if session is None:
            return True
        shared = share_opens and await get_session_access_role(db, session_id=session_id, user_id=user_id) is not None
        if session.project_id and not shared and _hidden(await db.get(Project, session.project_id), user_id):
            return True
    return False


def _session_not_found(request: Request) -> HTTPException:
    if (request.method, _route_path(request)) == TURN_ROUTE:
        from ...api.routes.sessions._sessions_turn_routes import api_refusal_http_exception

        return api_refusal_http_exception(TurnRefusal(TurnRefusalState.SESSION_NOT_FOUND, SESSION_NOT_FOUND_DETAIL))
    return HTTPException(status_code=404, detail=SESSION_NOT_FOUND_DETAIL)


def _route_path(request: Request) -> str:
    return getattr(request.scope.get("route"), "path", "")


def _named_ids(request: Request) -> tuple[set[str], set[str]]:
    unread = _route_path(request) in OWN_SESSION_ROUTES | CHAT_SHELL_ROUTES
    sessions = set() if unread else _named(request, SESSION_KEYS, SESSION_KEYS)
    return _named(request, PATH_KEYS, QUERY_KEYS), sessions


async def _refuse_hidden(request: Request, db: AsyncSession, user: User | None, workspaces: set[str],
                         sessions: set[str]) -> None:
    if user is None or not await is_global_admin(db, str(user.id)):
        return
    share_opens = (request.method, _route_path(request)) in SESSION_CONTENT_ROUTES
    if await _refused_session(db, str(user.id), sessions, share_opens):
        raise _session_not_found(request)
    for workspace_id in workspaces:
        if _hidden(await db.get(Project, workspace_id), str(user.id)):
            raise workspace_not_found()


async def api_viewer(user: User = Depends(get_current_user)) -> None:
    bind_request_viewer(str(user.id))


async def web_viewer(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    user, _detail = await load_active_principal(request, db)
    bind_request_viewer(str(user.id) if user is not None else None)


async def api_private_workspace_gate(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    workspaces, sessions = _named_ids(request)
    if workspaces or sessions:
        await _refuse_hidden(request, db, user, workspaces, sessions)


async def web_private_workspace_gate(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    workspaces, sessions = _named_ids(request)
    if workspaces or sessions:
        user, _detail = await load_active_principal(request, db)
        await _refuse_hidden(request, db, user, workspaces, sessions)


async def anonymous_viewer() -> None:
    # A route without a session principal reads as nobody until its own principal check binds one
    # (agent_gateway.identity, the device channel, each WebSocket's credential).
    bind_request_viewer(None)


def _gated(route: object) -> object:
    if isinstance(route, APIWebSocketRoute):
        gated = copy.copy(route)
        gated.dependencies = [Depends(anonymous_viewer), *route.dependencies]
        return gated
    if not isinstance(route, APIRoute):
        return route
    principal = route_principal(route)
    if principal is RoutePrincipal.API:
        viewer, gates = api_viewer, [Depends(api_private_workspace_gate)]
    elif principal is RoutePrincipal.WEB:
        viewer, gates = web_viewer, [Depends(web_private_workspace_gate)]
    else:
        viewer, gates = anonymous_viewer, []
    gated = copy.copy(route)
    gated.dependencies = [Depends(viewer), *route.dependencies, *gates]
    return gated


def with_private_workspace_gate(router: APIRouter) -> APIRouter:
    gated = copy.copy(router)
    gated.routes = [_gated(route) for route in router.routes]
    return gated


__all__ = ["CHAT_SHELL_ROUTES", "OWN_SESSION_ROUTES", "SESSION_CONTENT_ROUTES", "with_private_workspace_gate"]
