"""ASGI boundary that refuses cross-site panel mutations."""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request

from ...config import Settings, get_settings
from ...panel_csrf_policy import (
    CSRF_REJECTION_DETAIL,
    CSRF_REJECTION_STATUS,
    evaluate_panel_mutation,
    is_guarded_panel_path,
)
from ...services.request_context import get_current_request_id, safe_request_id

logger = logging.getLogger(__name__)


def request_id_for_scope(scope: Any) -> str | None:
    state = scope.get("state")
    candidate = state.get("request_id") if isinstance(state, dict) else None
    return safe_request_id(candidate) or safe_request_id(get_current_request_id())


def rejection_body(request_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "error": CSRF_REJECTION_DETAIL,
            "detail": CSRF_REJECTION_DETAIL,
            "status_code": CSRF_REJECTION_STATUS,
            "request_id": request_id,
        }
    ).encode("utf-8")


async def _send_rejection(send: Any, request_id: str | None) -> None:
    body = rejection_body(request_id)
    await send(
        {
            "type": "http.response.start",
            "status": CSRF_REJECTION_STATUS,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class PanelCsrfBoundaryMiddleware:
    """Apply the panel same-origin policy before anything routes the request."""

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        self.app = app
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not is_guarded_panel_path(scope.get("path")):
            return await self.app(scope, receive, send)

        decision = evaluate_panel_mutation(Request(scope), self.settings)
        if decision.allowed:
            return await self.app(scope, receive, send)

        logger.warning(
            "Panel mutation refused by the same-origin boundary (method=%s reason=%s)",
            scope.get("method"),
            decision.reason,
        )
        return await _send_rejection(send, request_id_for_scope(scope))


__all__ = ["PanelCsrfBoundaryMiddleware", "rejection_body", "request_id_for_scope"]
