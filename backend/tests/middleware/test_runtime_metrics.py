"""Runtime metrics on /metrics (services/observability/runtime_metrics.py): request latency by route template, the
database pool and the requests it made give up, event loop lag, process and build."""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import QueuePool

from app.middleware.telemetry.observability import observability_middleware
from app.services.observability import runtime_metrics
from tests.observability_support import admin_user, call_as


@pytest.fixture(autouse=True)
def _empty():
    runtime_metrics.reset()
    yield
    runtime_metrics.reset()


def _value(text: str, line_start: str) -> float:
    found = [line for line in text.splitlines() if line.startswith(line_start + " ")]
    assert len(found) == 1, (line_start, [line for line in text.splitlines() if line.startswith(line_start[:30])])
    return float(found[0].rsplit(" ", 1)[1])


@pytest.mark.asyncio
async def test_request_latency_by_route_template_process_and_build_are_on_metrics(client, db):
    admin = await admin_user(db)
    await call_as(client, "GET", "/metrics", admin)

    text = (await call_as(client, "GET", "/metrics", admin)).text  # shows the first scrape

    assert _value(text, 'octryx_api_request_duration_seconds_count{endpoint="/metrics",method="GET"}') == 1
    assert _value(text, 'octryx_api_request_duration_seconds_bucket{endpoint="/metrics",method="GET",le="+Inf"}') == 1
    assert _value(text, "process_resident_memory_bytes") > 0
    assert _value(text, "process_cpu_seconds_total") > 0
    assert any(line.startswith('octryx_build_info{version="') and line.endswith(" 1") for line in text.splitlines())


def test_the_pool_gauges_show_what_is_checked_out():
    pool = QueuePool(lambda: sqlite3.connect(":memory:"), pool_size=5, max_overflow=10)

    class Engine:
        sync_engine = type("Sync", (), {"pool": pool})()

    held = pool.connect()
    text = "\n".join(runtime_metrics.render(Engine(), app_version="1.2.3"))
    held.close()

    assert _value(text, "octryx_db_pool_size") == 5
    assert _value(text, "octryx_db_pool_max_overflow") == 10
    assert _value(text, 'octryx_db_pool_connections{state="checked_out"}') == 1
    assert 'octryx_build_info{version="1.2.3"} 1' in text


@pytest.mark.asyncio
async def test_a_request_that_waited_in_vain_for_a_pooled_connection_is_counted():
    class Request:
        method, scope = "GET", {}
        url = type("Url", (), {"path": "/api/v1/runs"})()

    async def no_connection(_request):
        raise PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")

    with pytest.raises(PoolTimeoutError):
        await observability_middleware(Request(), no_connection)

    text = "\n".join(runtime_metrics.render(object(), app_version="x"))
    assert _value(text, "octryx_db_pool_timeouts_total") == 1
    assert _value(text, 'octryx_api_request_duration_seconds_count{endpoint="/api/v1/runs",method="GET"}') == 1


@pytest.mark.asyncio
async def test_a_blocked_event_loop_shows_as_lag():
    runtime_metrics.ensure_loop_monitor()
    await asyncio.sleep(0.05)
    time.sleep(runtime_metrics.LAG_TICK_SECONDS + 0.4)  # blocks the loop
    await asyncio.sleep(0.1)

    lag = runtime_metrics.event_loop_lag()
    assert lag is not None and lag >= 0.3
