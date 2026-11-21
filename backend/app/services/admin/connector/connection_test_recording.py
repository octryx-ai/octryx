"""A manual connection test of a *saved* connection is also a health check.

So a card never says "Unhealthy" next to a test that just said "Connected": a test of the saved
connection records its outcome as that connector's health (global or per Workspace), exactly like the refresh
(``connector_health/service.py``): status, response time and the fixed summary. Only a test of the
*global* connection also feeds the per-connector circuit breaker; a Workspace test records its own
health only, so one Workspace's connection never opens the breaker for every Workspace. The
breaker is keyed per connection scope and never fed by ``no_test`` (``connector_health/breaker_scope.py``).
A test with typed, unsaved values is never recorded: it says nothing about what is saved.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...connector_health import upsert_connector_health
from ...connector_health.breaker_scope import check_status, record_platform_check

RunConnectionTest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def run_recorded_connection_test(
    db: AsyncSession,
    *,
    tool_name: str,
    project_id: str | None,
    config: dict[str, Any],
    run_connection_test: RunConnectionTest,
) -> dict[str, Any]:
    """Run the test on the saved, resolved ``config``, record it as health, and return the result."""
    started = time.perf_counter()
    result = await run_connection_test(tool_name, config)
    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = str(result.get("summary") or "").strip()
    details = str(result.get("details") or "").strip()
    status = check_status(result)
    await upsert_connector_health(
        db,
        connector_name=tool_name,
        project_id=project_id,
        status=status,
        response_time_ms=duration_ms,
        error="" if status != "error" else (summary or details),
        details=details or summary,
    )
    if project_id is None:
        await record_platform_check(db, tool_name, status, summary or details or "connector test failed")
    await db.commit()
    return result


__all__ = ["run_recorded_connection_test"]
