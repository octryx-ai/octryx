"""Every request slower than a threshold is logged with its route, so a stall has a name.

the local API stood still for minutes (12:40-12:46, 12:55-13:04): no log said which request held
the event loop. The cause was module compilation inside the loop (no bytecode in the container); this log is the
cheap guard that names the next one. Pure ASGI (no body re-streaming), threshold ``OCTRYX_SLOW_REQUEST_SECONDS``
(default 1.0).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("octryx.slow_requests")
DEFAULT_THRESHOLD_SECONDS = 1.0


def threshold_seconds() -> float:
    try:
        return float(os.environ.get("OCTRYX_SLOW_REQUEST_SECONDS") or DEFAULT_THRESHOLD_SECONDS)
    except ValueError:
        return DEFAULT_THRESHOLD_SECONDS


def route_of(scope: dict[str, Any]) -> str:
    """The route's path template (``/api/v1/workflow-runs/{run_id}``) when the router matched one, else the path."""
    route = scope.get("route")
    return str(getattr(route, "path", "") or scope.get("path") or "")


class SlowRequestLogMiddleware:
    def __init__(self, app: Any, threshold: float | None = None) -> None:
        self.app = app
        self.threshold = threshold if threshold is not None else threshold_seconds()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            seconds = time.perf_counter() - started
            if seconds >= self.threshold:
                logger.warning("slow_request method=%s route=%s seconds=%.2f", scope.get("method"),
                               route_of(scope), seconds)
