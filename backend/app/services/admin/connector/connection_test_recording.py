"""A manual connection test of a *saved* connection is also a health check."""

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
