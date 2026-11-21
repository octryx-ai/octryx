from __future__ import annotations

import time

from fastapi import Request
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from ...services.observability import record_request_counter
from ...services.observability.runtime_metrics import record_pool_timeout


def _endpoint(request: Request) -> str:
    endpoint = getattr(getattr(request.scope.get("route"), "path_format", None), "strip", lambda: None)()
    return endpoint or request.url.path


async def observability_middleware(request: Request, call_next):
    """Counts every request in memory (Prometheus counter + Health window); nothing is written per request."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        if isinstance(exc, PoolTimeoutError):  # no pooled connection within db_pool_timeout
            record_pool_timeout()
        record_request_counter(_endpoint(request), request.method, 500, int((time.perf_counter() - started) * 1000))
        raise
    endpoint = _endpoint(request)
    if not endpoint.startswith("/admin/static"):
        record_request_counter(endpoint, request.method, response.status_code,
                               int((time.perf_counter() - started) * 1000))
    return response
