"""A request over the threshold is logged with its route template, so an API stall has a name."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.telemetry.slow_requests import SlowRequestLogMiddleware


def _app(threshold: float) -> FastAPI:
    app = FastAPI()

    @app.get("/runs/{run_id}")
    async def slow(run_id: str):
        await asyncio.sleep(0.05)
        return {"id": run_id}

    app.add_middleware(SlowRequestLogMiddleware, threshold=threshold)
    return app


def test_a_slow_request_is_logged_with_its_route_and_a_fast_one_is_not(caplog):
    with caplog.at_level(logging.WARNING, logger="octryx.slow_requests"):
        assert TestClient(_app(0.01)).get("/runs/abc").status_code == 200
        assert TestClient(_app(5.0)).get("/runs/abc").status_code == 200
    lines = [r.getMessage() for r in caplog.records if r.name == "octryx.slow_requests"]
    assert len(lines) == 1 and "route=/runs/{run_id}" in lines[0] and "method=GET" in lines[0]
