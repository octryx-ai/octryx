"""ASGI admission boundary for multipart request bytes."""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.datastructures import Headers

from ...config import Settings, get_settings
from ...multipart_admission_policy import (
    CONTENT_LENGTH_MALFORMED,
    declared_content_length,
    is_multipart_content_type,
    resolve_request_limit,
    route_path,
)

logger = logging.getLogger(__name__)

REASON_DECLARED_LENGTH = "declared_content_length"
REASON_STREAMED_BYTES = "streamed_request_bytes"
REASON_MALFORMED_FRAMING = "malformed_content_length"

STATE_TOO_LARGE = "payload_too_large"
STATE_MALFORMED_FRAMING = "malformed_request_framing"

TOO_LARGE_STATUS = 413
TOO_LARGE_DETAIL = "Request body exceeds the upload limit for this endpoint."

MALFORMED_FRAMING_STATUS = 400
MALFORMED_FRAMING_DETAIL = "Request framing is invalid."


def _fixed_body(detail: str, status: int) -> bytes:
    return json.dumps(
        {"error": detail, "detail": detail, "status_code": status, "request_id": None}
    ).encode("utf-8")


_TOO_LARGE_BODY = _fixed_body(TOO_LARGE_DETAIL, TOO_LARGE_STATUS)
_MALFORMED_FRAMING_BODY = _fixed_body(MALFORMED_FRAMING_DETAIL, MALFORMED_FRAMING_STATUS)


class _AdmissionAbortError(OSError):
    pass


class _BudgetedBody:
    def __init__(self, receive: Any, limit: int) -> None:
        self._receive = receive
        self._limit = limit
        self.received = 0
        self.rejected = False

    async def __call__(self) -> Any:
        if self.rejected:
            # A consumer that keeps reading after the abort must not be able to
            # resume the stream at the byte where it was cut.
            raise _AdmissionAbortError()
        message = await self._receive()
        if message.get("type") != "http.request":
            return message
        self.received += len(message.get("body") or b"")
        if self.received > self._limit:
            self.rejected = True
            raise _AdmissionAbortError()
        return message


class _GuardedResponse:
    def __init__(self, send: Any, body: _BudgetedBody) -> None:
        self._send = send
        self._body = body
        self.started = False

    async def __call__(self, message: Any) -> None:
        if self._body.rejected and not self.started:
            return
        if message.get("type") == "http.response.start":
            self.started = True
        await self._send(message)


async def _send_rejection(send: Any, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class MultipartAdmissionMiddleware:
    """Reject oversized multipart requests before anything parses them."""

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        self.app = app
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if not is_multipart_content_type(headers.get("content-type")):
            return await self.app(scope, receive, send)

        route_policy, limit = resolve_request_limit(
            route_path(scope.get("path"), scope.get("root_path")),
            global_limit=self.settings.max_multipart_request_bytes,
        )
        framing, declared = declared_content_length(headers)
        if framing == CONTENT_LENGTH_MALFORMED:
            # Ambiguous framing is refused, never bounded by counting: the budget
            # would be enforced against a length the next hop may not agree with.
            self._log_rejection(
                scope,
                route_policy,
                limit,
                REASON_MALFORMED_FRAMING,
                state=STATE_MALFORMED_FRAMING,
            )
            return await _send_rejection(send, MALFORMED_FRAMING_STATUS, _MALFORMED_FRAMING_BODY)
        if declared is not None and declared > limit:
            self._log_rejection(scope, route_policy, limit, REASON_DECLARED_LENGTH)
            return await _send_rejection(send, TOO_LARGE_STATUS, _TOO_LARGE_BODY)

        body = _BudgetedBody(receive, limit)
        response = _GuardedResponse(send, body)
        try:
            await self.app(scope, body, response)
        except Exception:
            if not body.rejected:
                raise
            # Expected: the abort raised inside ``receive`` surfaced through the
            # parser (or a BaseHTTPMiddleware wrapping it). The 413 below is the
            # answer to it, so the failure is not propagated as a server error.
        if not body.rejected:
            return
        self._log_rejection(scope, route_policy, limit, REASON_STREAMED_BYTES)
        if response.started:
            # Nothing can replace a response the application already began.
            logger.warning(
                "Multipart request exceeded its byte budget after the response started "
                "(route_policy=%s method=%s limit_bytes=%s)",
                route_policy,
                scope.get("method"),
                limit,
            )
            return
        await _send_rejection(send, TOO_LARGE_STATUS, _TOO_LARGE_BODY)

    def _log_rejection(
        self,
        scope: Any,
        route_policy: str,
        limit: int,
        reason: str,
        *,
        state: str = STATE_TOO_LARGE,
    ) -> None:
        logger.warning(
            "Multipart request rejected before parsing "
            "(state=%s route_policy=%s method=%s limit_bytes=%s reason=%s)",
            state,
            route_policy,
            scope.get("method"),
            limit,
            reason,
        )


def log_admission_configuration(settings: Settings | None = None) -> int:
    """Log the active multipart ceiling once at startup and return it."""
    resolved = settings or get_settings()
    limit = int(resolved.max_multipart_request_bytes)
    logger.info("Multipart admission boundary active (max_multipart_request_bytes=%s)", limit)
    return limit


__all__ = [
    "MALFORMED_FRAMING_DETAIL",
    "MALFORMED_FRAMING_STATUS",
    "REASON_DECLARED_LENGTH",
    "REASON_MALFORMED_FRAMING",
    "REASON_STREAMED_BYTES",
    "STATE_MALFORMED_FRAMING",
    "STATE_TOO_LARGE",
    "TOO_LARGE_DETAIL",
    "TOO_LARGE_STATUS",
    "MultipartAdmissionMiddleware",
    "log_admission_configuration",
]
