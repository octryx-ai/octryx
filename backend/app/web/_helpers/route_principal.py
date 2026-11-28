"""Which principal dependency a route authenticates with, so a gate in front of it decides for the same caller."""

from __future__ import annotations

from enum import Enum

from fastapi.routing import APIRoute

from ...services.auth.service import get_current_user

WEB_ROUTER_PACKAGE = "app.web.routers."


class RoutePrincipal(Enum):
    API = "api"  # get_current_user: API key, then bearer, then cookie
    WEB = "web"  # cookie_principal.load_active_principal: cookie, then bearer
    NONE = "none"


def depends_on(route: APIRoute, call: object) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        if dependant.call is call:
            return True
        pending.extend(dependant.dependencies)
    return False


def route_principal(route: APIRoute) -> RoutePrincipal:
    if depends_on(route, get_current_user):
        return RoutePrincipal.API
    if str(route.endpoint.__module__).startswith(WEB_ROUTER_PACKAGE):
        return RoutePrincipal.WEB
    return RoutePrincipal.NONE


__all__ = ["WEB_ROUTER_PACKAGE", "RoutePrincipal", "depends_on", "route_principal"]
