"""An internal ``/metrics`` listener without authentication, for a Prometheus in the same private network.

On a local stack Prometheus scrapes the api and the worker directly, with no API
key and no token. So this listener does not answer on the api port. It runs on a port of its own, which a deployment
opens only to its private network (compose: no ``ports:`` entry) and never publishes. It is off unless
``OCTRYX_METRICS_PORT`` is set, so a deployment that sets nothing (Helm, the plain ``docker-compose.yml``)
keeps the authenticated ``/metrics`` of ``endpoint_access`` and nothing else.

The api and the worker each serve their own process's metrics, on different ports when they share a network
namespace (the local pod). It answers GET/HEAD ``/metrics`` only; any other path is 404, any other method 405.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping

logger = logging.getLogger(__name__)

METRICS_PORT_ENV = "OCTRYX_METRICS_PORT"
METRICS_HOST_ENV = "OCTRYX_METRICS_HOST"
# All interfaces of the process's network namespace; the deployment keeps the port private.
DEFAULT_METRICS_HOST = "0.0.0.0"  # noqa: S104 - reachable only where the deployment opens the port
_REQUEST_TIMEOUT_SECONDS = 5.0
_MAX_REQUEST_BYTES = 8192
_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}

Render = Callable[[], Awaitable[str]]


def metrics_port(env: Mapping[str, str] | None = None) -> int | None:
    """The listener's port; ``None`` (off) when unset or ``off``."""
    source = os.environ if env is None else env
    raw = str(source.get(METRICS_PORT_ENV) or "").strip().lower()
    if raw in {"", "off", "none", "disabled"}:
        return None
    port = int(raw)
    if not 0 <= port <= 65535:
        raise ValueError(f"{METRICS_PORT_ENV} must be a TCP port, got {raw!r}")
    return port


class MetricsListener:
    """A tiny HTTP/1.1 responder for GET/HEAD ``/metrics``, rendered by ``render`` on every scrape."""

    def __init__(self, render: Render, *, host: str, port: int, role: str) -> None:
        self._render = render
        self._host = host
        self._port = port
        self._role = role
        self._server: asyncio.base_events.Server | None = None

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, host=self._host, port=self._port)
        logger.info("metrics_listener_listening", extra={"role": self._role, "host": self._host, "port": self.port})

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()

    async def _answer(self, method: str, path: str) -> tuple[int, str, bytes]:
        if path.split("?", 1)[0] != "/metrics":
            return 404, "text/plain; charset=utf-8", b"not found\n"
        if method not in {"GET", "HEAD"}:
            return 405, "text/plain; charset=utf-8", b"method not allowed\n"
        try:
            return 200, _CONTENT_TYPE, (await self._render()).encode()
        except Exception:  # noqa: BLE001 - a failed render is a 500 for this scrape, never a crash of the listener
            logger.exception("metrics_listener_render_failed", extra={"role": self._role})
            return 500, "text/plain; charset=utf-8", b"render failed\n"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        method = "GET"
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=_REQUEST_TIMEOUT_SECONDS)
            if len(head) > _MAX_REQUEST_BYTES:
                raise ValueError("request head too large")
            parts = head.decode("latin-1").split("\r\n", 1)[0].split()
            if len(parts) < 2:
                raise ValueError("malformed request line")
            method, path = parts[0].upper(), parts[1]
            status, content_type, payload = await self._answer(method, path)
        except Exception:  # noqa: BLE001 - a malformed request gets a 400
            status, content_type, payload = 400, "text/plain; charset=utf-8", b"bad request\n"
        head_bytes = (
            f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(payload)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
        ).encode()
        try:
            writer.write(head_bytes if method == "HEAD" else head_bytes + payload)
            await writer.drain()
        except Exception:  # noqa: BLE001 - the scraper went away
            pass
        finally:
            writer.close()


async def start_metrics_listener(render: Render, *, role: str,
                                 env: Mapping[str, str] | None = None) -> MetricsListener | None:
    """Start the listener when ``OCTRYX_METRICS_PORT`` is set; ``None`` when it is off."""
    port = metrics_port(env)
    if port is None:
        return None
    source = os.environ if env is None else env
    listener = MetricsListener(render, host=str(source.get(METRICS_HOST_ENV) or "").strip() or DEFAULT_METRICS_HOST,
                               port=port, role=role)
    await listener.start()
    return listener


__all__ = ["DEFAULT_METRICS_HOST", "METRICS_HOST_ENV", "METRICS_PORT_ENV", "MetricsListener", "metrics_port",
           "start_metrics_listener"]
