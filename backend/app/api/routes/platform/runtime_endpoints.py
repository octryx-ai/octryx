"""Health and metrics endpoints; access is decided in services/observability/endpoint_access.py."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ....config import get_settings
from ....runtime_lifecycle import get_platform_runtime, set_runtime_session_factory
from ....services.observability.endpoint_access import health_body_for, require_metrics_reader

router = APIRouter()


def _runtime(request: Request):
    session_factory = getattr(request.app.state, "async_session_factory", None)
    if session_factory is not None:
        set_runtime_session_factory(session_factory)
    return get_platform_runtime()


@router.get("/api/v1/health")
async def health(request: Request):
    full = await _runtime(request).health_checks(app_version=get_settings().app_version)
    return await health_body_for(request, full)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request):
    await require_metrics_reader(request)
    payload = await _runtime(request).metrics_payload()
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4")
