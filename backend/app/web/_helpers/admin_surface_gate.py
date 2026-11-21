"""The admin-surface gate: every state-changing admin route refuses a non-admin before it runs.

An *admin surface* route is a state-changing (``POST``/``PUT``/``PATCH``/``DELETE``) route whose
served path has an ``admin`` or ``panel`` segment, under any mount (``/admin/...``,
``/api/v1/admin/...``, ``/chat/api/panel/...``). The gate is a dependency on every router the
application includes (``http_setup.py``), so a new route is covered without any bookkeeping, and
it runs before request-body validation, so a refused caller learns nothing about the body shape:

* no usable principal: 401 with the same detail the web principal owner uses; a
  server-rendered page route (``web/routers`` outside any ``api`` path) keeps its login
  redirect instead;
* an active principal that is not *admin-capable* — neither a global admin, nor a holder of
  one of the admin-panel permissions (:data:`ADMIN_PANEL_PERMISSIONS`), nor a Workspace
  ``admin``/``owner`` (project-scoped admin routes such as workflow definitions) — gets 403
  ``Admin role required``;
* otherwise the route runs and applies its own, finer check (global admin, a specific
  permission), which the gate never replaces. A route that already requires the admin role as a
  dependency (``services/auth/admin_principal.get_current_admin_user``) is left to it.

The only exceptions are the intentionally user-level routes that are also served under the
``/admin`` mount, listed with their reason in ``admin_surface_user_routes.py``.

Admin-only mutations whose path has no ``admin``/``panel`` segment (root-mounted chat routes such
as ``/budget-policies``, ``/api/v1`` routes that check the admin role inside the handler) are an
explicit, exact list (``admin_surface_root_routes.py``); for them the gate requires the global
admin role, the role their handlers require. Nothing is written on the refusal paths; the
principal is read in a short session of its own.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from ...models import User
from ...services.admin.governance.admin_access_service import is_admin_capable, is_global_admin
from .admin_surface_root_routes import ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH
from .admin_surface_user_routes import USER_LEVEL_ADMIN_SURFACE_ROUTES
from .cookie_principal import LOGIN_REDIRECT_PATH, UNAUTHENTICATED_DETAIL, load_active_principal

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ADMIN_SURFACE_SEGMENTS = frozenset({"admin", "panel"})
ADMIN_ROLE_REQUIRED_DETAIL = "Admin role required"
_PAGE_ROUTER_PACKAGE = "app.web.routers."
_ADMIN_DEPENDENCY_CACHE: dict[int, bool] = {}

def is_admin_surface_path(path: str) -> bool:
    return bool(ADMIN_SURFACE_SEGMENTS.intersection(str(path or "").strip("/").split("/")))


def requires_admin_capability(method: str, path: str) -> bool:
    """True for a state-changing admin-surface route that is not an explicit user-level one."""
    method = str(method or "").upper()
    return (
        method in MUTATING_METHODS
        and is_admin_surface_path(path)
        and (method, path) not in USER_LEVEL_ADMIN_SURFACE_ROUTES
    )


def requires_global_admin(method: str, path: str) -> bool:
    """True for a listed admin-only mutation outside the admin path (``admin_surface_root_routes``)."""
    return (str(method or "").upper(), path) in ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH




async def _principal(connection: HTTPConnection, db: AsyncSession) -> tuple[User | None, str]:
    from ...http_security import API_KEY_HEADER
    from ...services.api_key import authenticate_api_key

    raw_api_key = str(connection.headers.get(API_KEY_HEADER) or "").strip()
    if raw_api_key:
        try:
            user, _ = await authenticate_api_key(db, raw_api_key)
        except HTTPException as refused:
            return None, str(refused.detail)
        return user, ""
    return await load_active_principal(connection, db)


def _unauthenticated(route: object, detail: str) -> HTTPException:
    """401 on a JSON surface; the login redirect on a server-rendered page route."""
    endpoint_module = str(getattr(getattr(route, "endpoint", None), "__module__", ""))
    path_segments = str(getattr(route, "path", "")).strip("/").split("/")
    if endpoint_module.startswith(_PAGE_ROUTER_PACKAGE) and "api" not in path_segments:
        return HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_REDIRECT_PATH})
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail or UNAUTHENTICATED_DETAIL)


def _enforces_admin_itself(route: object) -> bool:
    """The route already requires the admin role as a dependency (``get_current_admin_user``).

    That dependency authenticates the way the route does (bearer, cookie or API key) and runs
    before body validation too, so the gate leaves the decision to it.
    """
    cached = _ADMIN_DEPENDENCY_CACHE.get(id(route))
    if cached is not None:
        return cached
    from ...services.auth.admin_principal import get_current_admin_user

    pending = list(getattr(getattr(route, "dependant", None), "dependencies", []) or [])
    found = False
    while pending and not found:
        dependant = pending.pop()
        found = dependant.call is get_current_admin_user
        pending.extend(dependant.dependencies)
    _ADMIN_DEPENDENCY_CACHE[id(route)] = found
    return found


async def admin_surface_gate(connection: HTTPConnection) -> None:
    """Router dependency: refuse a non-admin on a state-changing admin-surface route."""
    if connection.scope.get("type") != "http":
        return
    route = connection.scope.get("route")
    method, path = connection.scope.get("method", ""), getattr(route, "path", "")
    global_admin_only = requires_global_admin(method, path)
    if not global_admin_only and not requires_admin_capability(method, path):
        return
    if _enforces_admin_itself(route):
        return
    # The application's own session factory (``app.state``), the one its routes and workers use.
    async with connection.app.state.async_session_factory() as db:
        user, detail = await _principal(connection, db)
        if user is None:
            if global_admin_only:  # JSON routes all of them, also the root chat mounts
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail or UNAUTHENTICATED_DETAIL)
            raise _unauthenticated(route, detail)
        admitted = await is_global_admin(db, user.id) if global_admin_only else await is_admin_capable(db, user.id)
        if not admitted:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_ROLE_REQUIRED_DETAIL)


__all__ = [
    "ADMIN_ROLE_REQUIRED_DETAIL",
    "admin_surface_gate",
    "is_admin_surface_path",
    "requires_admin_capability",
    "requires_global_admin",
]
