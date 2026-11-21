"""ASGI admission boundary for multipart request bytes.

Installed directly inside the trusted-proxy boundary, therefore above every
application middleware, every router and every form parser. That position is the
whole point: FastAPI resolves a route's multipart body *before* it solves the
route's dependencies, so Starlette's parser — and its ``SpooledTemporaryFile`` for
any part over 1 MiB — runs while the request is still unauthenticated. The budget
has to be applied by whoever hands the body to that parser.

How the budget is applied:

- A declared ``Content-Length`` over the limit is answered immediately. The
  downstream application is never called and not one body byte is read.
- Otherwise ``receive`` is wrapped. Raw ``http.request`` byte counts are added up
  and the first message that would push the request past the limit is *not*
  delivered: the wrapper raises instead, so no consumer can mistake a bounded
  prefix for a complete body. The oversized chunk is dropped rather than parsed.
- The wrapper never buffers. Messages below the budget are passed through
  unchanged, so an accepted upload streams exactly as it does without this
  middleware, and a 512 MiB upload still costs the middleware nothing but a
  counter.

The abort signal is a private exception raised inside ``receive``. It stops the
parser at once, and it is caught here — *below* Starlette's
``ServerErrorMiddleware``, which is why the caller sees the fixed 413 instead of a
500. Any other exception is re-raised untouched. The signal subclasses ``OSError``
on purpose: ``MultiPartParser.parse`` closes every ``SpooledTemporaryFile`` it had
already created only for ``MultiPartException`` and ``OSError``
(``starlette/formparsers.py`` in 1.3.1), so a dishonest streaming overrun must
raise inside that tuple or the temporary file it caused is left open.

Catching the signal is not enough on its own: FastAPI wraps form parsing in
``except Exception -> HTTPException(400)``, so the application answers a request
it was never allowed to read. (``MultiPartException`` would be converted even
earlier, by Starlette's own ``Request._get_form``; ``OSError`` at least reaches
FastAPI unchanged, which is the second reason for that base class.) Once the budget is exhausted the ``send`` wrapper
therefore discards a response the application starts *afterwards*: the request was
already refused, so that response can only be a derivative of the refusal. A
response that had already started before the budget was hit is left alone — it
cannot be replaced, and truncating it would be worse than finishing it.

A request whose framing is ambiguous never gets that far: zero or one well-formed
``Content-Length`` is admissible, and anything else (empty, signed, non-numeric,
comma-joined, or a second occurrence) is answered with a fixed 400 without calling
downstream and without reading a byte. Counting bytes for such a request would
mean enforcing a budget against framing the next hop may read differently.

What is never recorded: body bytes, form fields, file names, authorization or
cookie headers, the client's own request path, and — for malformed framing — the
rejected header value. A rejection logs the fixed state, the matched route policy
identifier, the request method and the configured limit.
"""

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
    """One fixed rejection body, in the shape of the platform's error contract.

    Mirrors ``api.routes.error_contracts.build_error_payload``. Nothing from the
    request appears in it: the limit is deliberately not disclosed, the rejected
    header value is never echoed, and ``request_id`` is null because this boundary
    runs outside the request-context middleware that mints one.
    """
    return json.dumps(
        {"error": detail, "detail": detail, "status_code": status, "request_id": None}
    ).encode("utf-8")


_TOO_LARGE_BODY = _fixed_body(TOO_LARGE_DETAIL, TOO_LARGE_STATUS)
_MALFORMED_FRAMING_BODY = _fixed_body(MALFORMED_FRAMING_DETAIL, MALFORMED_FRAMING_STATUS)


class _AdmissionAbortError(OSError):
    """Internal signal that the byte budget was exhausted mid-stream.

    ``OSError`` is load-bearing, not decoration. ``MultiPartParser.parse`` wraps
    its read loop in ``except (MultiPartException, OSError)`` and closes every
    ``SpooledTemporaryFile`` it had already created before re-raising
    (``starlette/formparsers.py``, Starlette 1.3.1). An abort outside that tuple
    would leave the temporary file of a dishonest streaming overrun open for the
    garbage collector to notice. ``MultiPartException`` would also reach the
    cleanup, but Starlette's ``Request._get_form`` converts it into
    ``HTTPException(400)`` immediately; ``OSError`` survives to FastAPI's blanket
    body-parse handler instead, and the response guard below keeps that derived
    400 off the wire either way.
    """


class _BudgetedBody:
    """``receive`` wrapper that counts raw request bytes and stops at the limit."""

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
    """``send`` wrapper that records the response and drops refused answers.

    ``started`` is only set for messages that were actually forwarded, so a
    response the application begins after the budget was exhausted never counts as
    started and is replaced by the fixed 413.
    """

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
    """Answer one rejected request and close the connection.

    The connection is closed because the rest of the request body is never read:
    leaving it unread on a keep-alive connection would desynchronize the next
    request on the same socket.
    """
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
