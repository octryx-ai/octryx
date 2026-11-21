"""The platform worker process: the background workers, never the API.

``python -m app.worker_main`` builds the same :class:`~app.runtime_setup.PlatformRuntime` the API
lifespan uses and runs its startup with the background workers on (scheduler and task queue
dispatcher, channels and the channel router, intake pollers, knowledge projection, approval
timeouts, connector health, ...). It serves no API route. A minimal HTTP probe endpoint
(:class:`WorkerHealthServer`) answers on its own port:

* ``GET /livez``  200 while the event loop answers (liveness).
* ``GET /health`` 200 once startup completed and the critical loops run; 503 while starting,
  stopping or when the queue dispatcher or the runtime ownership loop has stopped (readiness).
* ``GET /metrics`` the agent counters of this process (``octryx_*``) for a Prometheus scraper presenting
  ``METRICS_SCRAPE_TOKEN`` as a bearer token; without the token 401.

With ``OCTRYX_METRICS_PORT`` set, the same counters are also served without authentication on that port
(``services/observability/metrics_listener.py``), for a Prometheus in the deployment's private network.

The API then runs with ``OCTRYX_DISABLE_BACKGROUND_WORKERS=1``. This process ignores that
flag: it exists to run the workers, so it always turns them on.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import signal
from collections.abc import Callable
from typing import Any

from .db import async_session_factory
from .runtime_lifecycle import get_platform_runtime
from .runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV, SKIP_CHAT_BUILD_ENV, SKIP_IMAGE_PLUGINS_ENV
from .services.observability.logging import configure_json_logging
from .services.observability.metrics_listener import start_metrics_listener

logger = logging.getLogger("octryx.worker")

HEALTH_PORT_ENV = "OCTRYX_WORKER_HEALTH_PORT"
HEALTH_HOST_ENV = "OCTRYX_WORKER_HEALTH_HOST"
DEFAULT_HEALTH_PORT = 8001
DEFAULT_HEALTH_HOST = "0.0.0.0"  # noqa: S104 - the kubelet probes the pod IP; the body carries no data
_REQUEST_TIMEOUT_SECONDS = 5.0
_MAX_REQUEST_BYTES = 8192


def health_port(env: dict[str, str] | None = None) -> int | None:
    """The probe port; ``None`` when set to ``off`` (no endpoint)."""
    source = os.environ if env is None else env
    raw = str(source.get(HEALTH_PORT_ENV) or "").strip().lower()
    if not raw:
        return DEFAULT_HEALTH_PORT
    if raw in {"off", "none", "disabled"}:
        return None
    port = int(raw)
    if not 0 <= port <= 65535:
        raise ValueError(f"{HEALTH_PORT_ENV} must be a TCP port, got {raw!r}")
    return port


def apply_worker_role_environment(env: Any = None) -> None:
    """This process runs the background workers and never builds or serves the chat frontend."""
    target = os.environ if env is None else env
    if str(target.get(DISABLE_BACKGROUND_WORKERS_ENV) or "").strip() not in {"", "0"}:
        logger.warning(
            "worker_role_overrides_disabled_background_workers",
            extra={"env": DISABLE_BACKGROUND_WORKERS_ENV, "value": target.get(DISABLE_BACKGROUND_WORKERS_ENV)},
        )
    target[DISABLE_BACKGROUND_WORKERS_ENV] = "0"
    target[SKIP_CHAT_BUILD_ENV] = "1"
    target[SKIP_IMAGE_PLUGINS_ENV] = "1"  # the API brings the image's plugins in


def _task_alive(task: Any) -> bool:
    return task is not None and not task.done()


def worker_health(runtime: Any, *, phase: str) -> tuple[int, dict[str, object]]:
    """Readiness of the worker process: started, and the loops it cannot work without still run."""
    if phase != "ready":
        return 503, {"status": phase, "role": "worker"}
    checks = {
        "runtime_ownership": bool(runtime.runtime_ownership_worker.is_running()),
        "task_queue_dispatcher": _task_alive(getattr(runtime.task_scheduler, "_queue_dispatch_task", None)),
    }
    healthy = all(checks.values())
    return (200 if healthy else 503), {"status": "ok" if healthy else "degraded", "role": "worker", "checks": checks}


class WorkerHealthServer:
    """A tiny HTTP/1.1 responder: GET/HEAD ``/livez`` and ``/health`` for kubelet probes, and GET ``/metrics`` (agent
    counters of this process, only with the scrape token) for Prometheus."""

    def __init__(self, runtime: Any, *, host: str, port: int) -> None:
        self._runtime = runtime
        self._host = host
        self._port = port
        self._server: asyncio.base_events.Server | None = None
        self.phase = "starting"

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, host=self._host, port=self._port)
        logger.info("worker_health_listening", extra={"host": self._host, "port": self.port})

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()

    async def _metrics(self, headers: dict[str, str]) -> tuple[int, str]:
        """The worker's agent counters for a scraper presenting ``metrics_scrape_token`` (no token: 401)."""
        from .config import get_settings
        from .services.observability.metrics_render import render_worker_metrics

        configured = str(get_settings().metrics_scrape_token or "").strip()
        scheme, _, presented = headers.get("authorization", "").partition(" ")
        if not (configured and scheme.lower() == "bearer"
                and hmac.compare_digest(configured.encode(), presented.strip().encode())):
            return 401, "unauthorized\n"
        return 200, await render_worker_metrics(async_session_factory)

    def _answer(self, method: str, path: str) -> tuple[int, dict[str, object]]:
        if method not in {"GET", "HEAD"}:
            return 405, {"status": "method_not_allowed"}
        route = path.split("?", 1)[0]
        if route == "/livez":
            return 200, {"status": "alive", "role": "worker"}
        if route in {"/health", "/healthz", "/readyz"}:
            return worker_health(self._runtime, phase=self.phase)
        return 404, {"status": "not_found"}

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=_REQUEST_TIMEOUT_SECONDS)
            if len(head) > _MAX_REQUEST_BYTES:
                raise ValueError("request head too large")
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            parts = request_line.split()
            method, path = (parts[0].upper(), parts[1]) if len(parts) >= 2 else ("", "")
            content_type = "application/json"
            if method == "GET" and path.split("?", 1)[0] == "/metrics":
                headers = {name.strip().lower(): value.strip()
                           for name, _, value in (line.partition(":") for line in header_lines if ":" in line)}
                status, text = await self._metrics(headers)
                payload, content_type = text.encode(), "text/plain; version=0.0.4; charset=utf-8"
            else:
                status, body = self._answer(method, path)
                payload = json.dumps(body).encode()
        except Exception:  # noqa: BLE001 - a malformed probe gets a 400, never a crash
            method, status, content_type = "GET", 400, "application/json"
            payload = json.dumps({"status": "bad_request"}).encode()
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
                  405: "Method Not Allowed"}.get(status, "Service Unavailable")
        head_bytes = (
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n"
            f"Content-Length: {len(payload)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
        ).encode()
        try:
            writer.write(head_bytes if method == "HEAD" else head_bytes + payload)
            await writer.drain()
        except Exception:  # noqa: BLE001 - the prober went away
            pass
        finally:
            writer.close()


async def main_async(
    *,
    stop_event: asyncio.Event | None = None,
    on_ready: Callable[[WorkerHealthServer | None], Any] | None = None,
    install_signal_handlers: bool = True,
) -> None:
    configure_json_logging()
    apply_worker_role_environment()
    runtime = get_platform_runtime(async_session_factory)
    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        logger.info("Worker shutdown requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM) if install_signal_handlers else ():
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    port = health_port()
    health = None
    if port is not None:
        health = WorkerHealthServer(runtime, host=os.environ.get(HEALTH_HOST_ENV) or DEFAULT_HEALTH_HOST, port=port)
        await health.start()
    metrics = await start_metrics_listener(_worker_metrics, role="worker")

    logger.info("Starting Octryx background worker runtime")
    try:
        await runtime.startup()
        if health is not None:
            health.phase = "ready"
        if on_ready is not None:
            on_ready(health)
        try:
            await stop_event.wait()
        finally:
            if health is not None:
                health.phase = "stopping"
            logger.info("Stopping Octryx background worker runtime")
            await runtime.shutdown()
    finally:
        if metrics is not None:
            await metrics.stop()
        if health is not None:
            await health.stop()


async def _worker_metrics() -> str:
    from .services.observability.metrics_render import render_worker_metrics

    return await render_worker_metrics(async_session_factory)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
