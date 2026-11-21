"""Gzip for complete text responses; streams, ranges and compressed bodies pass through untouched.

The API answers JSON (a Work board page is about 1.3 MB) and the server-rendered pages answer HTML, and before
this nothing on the way was compressed. Starlette's ``GZipMiddleware`` is not used because it also compresses
streamed bodies: it buffers each chunk in a ``GzipFile`` without flushing it, so an NDJSON or relay stream would
reach the client late and in bursts. Here only a body that arrives as **one** message is compressed, so a stream
of any media type is never held back:

- the response starts with a single ``http.response.body`` message (``more_body`` false);
- the status is a 2xx other than 204 and 206, and no ``Content-Range`` is set (a range answers exact bytes);
- no ``Content-Encoding`` is set (precompressed static assets, relayed upstream bodies);
- the media type is text, JSON, JavaScript, XML, SVG or WebAssembly, never ``text/event-stream``;
- the body is at least :data:`MINIMUM_SIZE` bytes, the request accepts ``gzip`` and
  ``Cache-Control`` does not say ``no-transform``.

Registered innermost (directly above the router) so it sees the route's own single body message; the
``BaseHTTPMiddleware`` layers above re-stream whatever passes through and would make every body look streamed.
The SPA's static files are compressed once and kept in memory by :mod:`app.web.static_files`.
"""

from __future__ import annotations

import gzip

import anyio
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Bodies below this size are sent as they are: the gzip frame and the CPU are not worth it.
MINIMUM_SIZE = 1024
#: Level 6 is zlib's default: close to level 9 in size at a fraction of its CPU on the single API process.
COMPRESS_LEVEL = 6
#: Larger bodies are compressed in a worker thread (zlib releases the GIL), so the event loop keeps serving.
THREAD_THRESHOLD = 64 * 1024

_TEXT_TYPES = frozenset({
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "application/json",
    "application/manifest+json",
    "application/xml",
    "application/xhtml+xml",
    "application/wasm",
    "image/svg+xml",
})
_EXCLUDED_TYPES = frozenset({"text/event-stream"})


def media_type_of(content_type: str | None) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def is_compressible_media_type(content_type: str | None) -> bool:
    """True for text-like bodies that gzip shrinks; never for an event stream or an already packed format."""
    media_type = media_type_of(content_type)
    if not media_type or media_type in _EXCLUDED_TYPES:
        return False
    if media_type.startswith("text/") or media_type in _TEXT_TYPES:
        return True
    return media_type.endswith(("+json", "+xml"))


def accepts_gzip(headers: Headers) -> bool:
    """Whether ``Accept-Encoding`` allows gzip (``gzip`` or ``*`` without ``q=0``)."""
    accepted: dict[str, bool] = {}
    for part in str(headers.get("accept-encoding") or "").split(","):
        token, _, params = part.strip().partition(";")
        coding = token.strip().lower()
        if not coding:
            continue
        refused = False
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    refused = float(value.strip() or "1") <= 0
                except ValueError:
                    refused = True
        accepted[coding] = not refused
    if "gzip" in accepted:
        return accepted["gzip"]
    return accepted.get("*", False)


def gzip_bytes(body: bytes, *, level: int = COMPRESS_LEVEL) -> bytes:
    # mtime=0: the same body always compresses to the same bytes (stable for caches and tests).
    return gzip.compress(body, compresslevel=level, mtime=0)


async def gzip_bytes_off_loop(body: bytes, *, level: int = COMPRESS_LEVEL) -> bytes:
    if len(body) < THREAD_THRESHOLD:
        return gzip_bytes(body, level=level)
    return await anyio.to_thread.run_sync(lambda: gzip_bytes(body, level=level))


def weak_etag(etag: str) -> str:
    """The ETag of the gzip representation: weak, so a revalidation still matches the file's own tag."""
    return etag if etag.startswith("W/") else f"W/{etag}"


def _eligible_start(start: Message) -> bool:
    status = int(start.get("status") or 200)
    if status < 200 or status >= 300 or status in (204, 206):
        return False
    headers = Headers(raw=start.get("headers") or [])
    if "content-encoding" in headers or "content-range" in headers:
        return False
    if "no-transform" in str(headers.get("cache-control") or "").lower():
        return False
    return is_compressible_media_type(headers.get("content-type"))


class ResponseCompressionMiddleware:
    """Pure ASGI middleware: gzip a complete text body, pass everything else through unchanged."""

    def __init__(self, app: ASGIApp, *, minimum_size: int = MINIMUM_SIZE) -> None:
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not accepts_gzip(Headers(scope=scope)):
            await self.app(scope, receive, send)
            return

        start: Message | None = None
        decided = False

        async def send_wrapper(message: Message) -> None:
            nonlocal start, decided
            if decided:
                await send(message)
                return
            if message["type"] == "http.response.start":
                start = message
                return
            decided = True
            if start is None:  # pragma: no cover - a body before its start is an ASGI protocol error
                await send(message)
                return
            body = message.get("body", b"") if message["type"] == "http.response.body" else b""
            single = message["type"] == "http.response.body" and not message.get("more_body", False)
            if not single or len(body) < self.minimum_size or not _eligible_start(start):
                await send(start)
                await send(message)
                return
            compressed = await gzip_bytes_off_loop(body)
            headers = MutableHeaders(raw=list(start.get("headers") or []))
            headers.add_vary_header("Accept-Encoding")
            if len(compressed) >= len(body):
                await send({**start, "headers": headers.raw})
                await send(message)
                return
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(compressed))
            if "etag" in headers:
                headers["ETag"] = weak_etag(headers["etag"])
            await send({**start, "headers": headers.raw})
            await send({**message, "body": compressed})

        await self.app(scope, receive, send_wrapper)
        if start is not None and not decided:  # pragma: no cover - a start without a body
            await send(start)


__all__ = [
    "MINIMUM_SIZE",
    "ResponseCompressionMiddleware",
    "accepts_gzip",
    "gzip_bytes",
    "gzip_bytes_off_loop",
    "is_compressible_media_type",
    "media_type_of",
    "weak_etag",
]
