from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from ...services.data_access import request_scope


class DataViewerScopeMiddleware:
    """Every request starts without a data viewer; the one its route's gate binds ends with the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        with request_scope():
            await self.app(scope, receive, send)
