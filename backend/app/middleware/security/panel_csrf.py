"""ASGI boundary that refuses cross-site panel mutations.

One boundary instead of ~250 route edits. The panel mutation routes span 21
router modules and two mount prefixes; a per-route check would have to be
repeated in each of them and could be forgotten by the next one added. Here the
rule is applied once, to every request, and
``tests/test_panel_mutation_inventory_gate.py`` proves that the set of routes it
covers is still the set of routes that exist.

Position in the stack — registered directly after
:class:`MultipartAdmissionMiddleware` in ``http_setup``, therefore *outside* it
and *inside* ``CORSMiddleware``:

- Outside the multipart boundary, and so above every body parser: a cross-site
  upload is refused before one byte of its body is read or spooled to disk.
- Inside CORS, so a refusal is still labelled for an allowed origin and a
  preflight is still answered by CORS itself (``OPTIONS`` is a safe method here
  in any case).
- Inside the trusted-proxy boundary, which is what makes ``scope["scheme"]``
  the *validated* scheme rather than a forwarded claim.
- Above the router, so the refusal precedes routing, dependency resolution,
  authentication, authorization, audit attribution and persistence.

The refusal is one fixed body. It does not name the path, the resource, the
origin that was rejected, or whether the target exists — the same 403 answers a
real and an invented panel resource, in this Workspace or another. Its only
per-request field is ``request_id``, which this boundary echoes from the request
context the outer middleware already established and which every response on
this application carries in its ``X-Request-ID`` header anyway; it is the
correlation handle the platform's error contract promises, and it says nothing
about the request that was refused. The log line carries only the enum-like
decision reason and the request method.
"""

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
    """The request id already established for this request, when there is one.

    ``request_context_middleware`` runs outside this boundary, so it has normally
    already validated or minted one and put it on the request scope; the
    contextvar is the fallback for a stack that sets only that. Both are
    re-validated through the single ``safe_request_id`` rule, so nothing
    caller-supplied reaches the response body unchecked. Returns ``None`` when
    this boundary runs without a request context at all — a fixed ``null`` rather
    than an invented id.
    """
    state = scope.get("state")
    candidate = state.get("request_id") if isinstance(state, dict) else None
    return safe_request_id(candidate) or safe_request_id(get_current_request_id())


def rejection_body(request_id: str | None = None) -> bytes:
    """The fixed 403 body, in the shape of the platform's error contract.

    Mirrors ``api.routes.error_contracts.build_error_payload``. Every field
    except ``request_id`` is a constant, so two refusals differ only by the
    correlation id the response header carries anyway.
    """
    return json.dumps(
        {
            "error": CSRF_REJECTION_DETAIL,
            "detail": CSRF_REJECTION_DETAIL,
            "status_code": CSRF_REJECTION_STATUS,
            "request_id": request_id,
        }
    ).encode("utf-8")


async def _send_rejection(send: Any, request_id: str | None) -> None:
    """Answer one refused request and close the connection.

    The request body is never read, so the connection cannot be reused: leaving
    unread bytes on a keep-alive socket would desynchronize the next request.
    """
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
