"""The admin-surface gate: every state-changing admin route refuses a non-admin before it runs."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.admin.governance.admin_access_service import is_admin_capable, is_global_admin
from ...services.auth.admin_principal import get_current_admin_user
from ...services.auth.service import get_current_user
from ...services.data_access import as_viewer
from .admin_surface_root_routes import ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH
from .admin_surface_user_routes import USER_LEVEL_ADMIN_SURFACE_ROUTES
from .cookie_principal import LOGIN_REDIRECT_PATH, UNAUTHENTICATED_DETAIL, load_active_principal
from .route_principal import RoutePrincipal, depends_on, route_principal

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ADMIN_SURFACE_SEGMENTS = frozenset({"admin", "panel"})
ADMIN_ROLE_REQUIRED_DETAIL = "Admin role required"
AdminCheck = Callable[[AsyncSession, str], Awaitable[bool]]


def is_admin_surface_path(path: str) -> bool:
    return bool(ADMIN_SURFACE_SEGMENTS.intersection(str(path or "").strip("/").split("/")))


def requires_admin_capability(method: str, path: str) -> bool:
    # A state-changing admin-surface route needs the admin capability unless it is an explicit user-level one.
    method = str(method or "").upper()
    return (
        method in MUTATING_METHODS
        and is_admin_surface_path(path)
        and (method, path) not in USER_LEVEL_ADMIN_SURFACE_ROUTES
    )


def requires_global_admin(method: str, path: str) -> bool:
    return (str(method or "").upper(), path) in ADMIN_ONLY_ROUTES_OUTSIDE_ADMIN_PATH


def _admin_check(request: Request) -> AdminCheck | None:
    method, path = request.method, _route_path(request)
    if requires_global_admin(method, path):
        return is_global_admin
    if requires_admin_capability(method, path):
        return is_admin_capable
    return None


def _route_path(request: Request) -> str:
    return getattr(request.scope.get("route"), "path", "")


def _unauthenticated(request: Request, detail: str) -> HTTPException:
    path = _route_path(request)
    if "api" not in path.strip("/").split("/") and not requires_global_admin(request.method, path):
        return HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_REDIRECT_PATH})
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail or UNAUTHENTICATED_DETAIL)


async def _refuse_non_admin(db: AsyncSession, user: User, admitted_by: AdminCheck) -> None:
    # The terminal router has no private-Workspace gate, so no request viewer is bound there.
    with as_viewer(user.id):
        admitted = await admitted_by(db, user.id)
    if not admitted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_ROLE_REQUIRED_DETAIL)


async def api_admin_surface_gate(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    admitted_by = _admin_check(request)
    if admitted_by is not None:
        await _refuse_non_admin(db, user, admitted_by)


async def web_admin_surface_gate(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    admitted_by = _admin_check(request)
    if admitted_by is None:
        return
    user, detail = await load_active_principal(request, db)
    if user is None:
        raise _unauthenticated(request, detail)
    await _refuse_non_admin(db, user, admitted_by)


async def no_principal_admin_surface_gate(request: Request) -> None:
    if _admin_check(request) is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=UNAUTHENTICATED_DETAIL)


_GATES = {
    RoutePrincipal.API: api_admin_surface_gate,
    RoutePrincipal.WEB: web_admin_surface_gate,
    RoutePrincipal.NONE: no_principal_admin_surface_gate,
}


def enforces_admin_itself(route: APIRoute) -> bool:
    return depends_on(route, get_current_admin_user)


def _gated(route: object) -> object:
    if not isinstance(route, APIRoute) or enforces_admin_itself(route):
        return route
    gated = copy.copy(route)
    gated.dependencies = [Depends(_GATES[route_principal(route)]), *route.dependencies]
    return gated


def with_admin_surface_gate(router: APIRouter) -> APIRouter:
    gated = copy.copy(router)
    gated.routes = [_gated(route) for route in router.routes]
    return gated


__all__ = [
    "ADMIN_ROLE_REQUIRED_DETAIL",
    "enforces_admin_itself",
    "is_admin_surface_path",
    "requires_admin_capability",
    "requires_global_admin",
    "with_admin_surface_gate",
]
