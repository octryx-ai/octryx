"""ASGI boundary that applies the validated trusted-proxy policy.

Installed as the outermost application middleware so every downstream
middleware, route, and policy sees one consistent client address and scheme.
The resolved identity is recorded in the scope state first, which keeps the
original transport peer and the trust decision available to peer-based policies
(the local-debug auth-cookie exemption) after ``scope["client"]`` has been set
to the effective client.

Uvicorn's ``ProxyHeadersMiddleware`` is disabled on every launch path, so this
is the only place where a forwarded header can influence the request.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from ...trusted_proxy_policy import record_client_identity, resolve_scope_client_identity

_BOUNDARY_SCOPE_TYPES = frozenset({"http", "websocket"})


class TrustedProxyBoundaryMiddleware:
    """Resolve and apply the effective client identity for each connection."""

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        self.app = app
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in _BOUNDARY_SCOPE_TYPES:
            return await self.app(scope, receive, send)

        identity = resolve_scope_client_identity(scope, self.settings)
        record_client_identity(scope, identity)
        if identity.is_forwarded:
            # The forwarded hop carries no client port, matching uvicorn's
            # ProxyHeadersMiddleware contract.
            scope["client"] = (identity.client_address, 0)
        if identity.scheme:
            scope["scheme"] = identity.scheme
        return await self.app(scope, receive, send)


__all__ = ["TrustedProxyBoundaryMiddleware"]
