"""The private-Workspace gate: somebody else's private Workspace does not exist for the caller.

A router dependency on every included router (``http_setup.ADMIN_SURFACE_DEPENDENCIES``), next to the admin-surface
gate, so a new route is covered without bookkeeping. When a request names a Workspace (a ``project_id``,
``workspace_id`` or ``projectId`` path parameter, or a ``project_id`` / ``workspace_id`` query parameter) and that
Workspace is a private one, the owner passes, and a platform admin (the admin role, ``is_global_admin``) or no caller
at all gets the one answer of a Workspace the caller may not see (``access_control.workspace_not_found``: 404
``project_not_found``). Everybody else, a holder of a delegated admin-panel permission without the admin role
included, is an ordinary outsider here: they reach a Workspace through membership only, which nobody but the owner has
in a private one, so the gate leaves them to the route, which answers exactly as for a shared Workspace they are no
member of, i.e. as for an unknown id (``tests/test_workspace_id_routes.py``); a gate answer of its own would differ
from a route that answers an unknown id with a role refusal, a typed 409 or an empty list. The routes a delegated
permission opens without membership (the project-access routes, ``projects`` read/write) refuse somebody else's private
Workspace themselves, with their own answer for a missing project (``admin_project_access_service
.require_administrable_project``). Requests that name no private Workspace cost one primary-key lookup per named id and
nothing else.

This is the net under the admin panel's per-Workspace routes (config, connectors, members, resources, skills,
composition, design, workers): they check the admin role, never membership. Lists and scopes that do not name a
Workspace leave other people's private ones out where they are built (``project.private_workspace``).
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

from ...services.access_control import workspace_not_found
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.project.private_workspace import private_project, private_role
from .admin_surface_gate import _principal

PATH_KEYS = ("project_id", "workspace_id", "projectId", "workspaceId")
QUERY_KEYS = ("project_id", "workspace_id")
# Review second round: a session named in the path or query is checked by its Workspace too (flow generation,
# effective setup, exports, … by session id).
SESSION_KEYS = ("session_id", "sessionId")


def named_workspaces(connection: HTTPConnection) -> set[str]:
    path = connection.scope.get("path_params") or {}
    named = {str(path.get(key) or "").strip() for key in PATH_KEYS}
    named |= {str(connection.query_params.get(key) or "").strip() for key in QUERY_KEYS}
    return {value[:64] for value in named if value}


def named_sessions(connection: HTTPConnection) -> set[str]:
    path = connection.scope.get("path_params") or {}
    named = {str(path.get(key) or "").strip() for key in SESSION_KEYS}
    named |= {str(connection.query_params.get(key) or "").strip() for key in SESSION_KEYS}
    return {value[:64] for value in named if value}


async def private_workspace_gate(connection: HTTPConnection) -> None:
    if connection.scope.get("type") != "http":
        return
    named = named_workspaces(connection)
    sessions = named_sessions(connection)
    if not named and not sessions:
        return
    async with connection.app.state.async_session_factory() as db:
        if sessions:
            from ...models import Session  # noqa: PLC0415

            for session_id in sessions:
                row = await db.get(Session, session_id)
                if row is not None and row.project_id:
                    named.add(str(row.project_id))
        if not named:
            return
        private = [project for project in [await private_project(db, value) for value in named] if project]
        if not private:
            return
        user, _detail = await _principal(connection, db)
        if user is not None and all(private_role(project, str(user.id)) is not None for project in private):
            return
        if user is None or await is_global_admin(db, str(user.id)):
            raise workspace_not_found()
        # Anybody else (a delegated admin-panel permission holder too) reaches a Workspace through membership only,
        # which nobody but the owner has in a private one: the route answers exactly as for any Workspace the caller
        # is no member of, i.e. as for an unknown id.


__all__ = ["named_workspaces", "private_workspace_gate"]
