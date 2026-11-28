from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db_concurrency_observability import _DB_CONCURRENCY_COUNTER
from ..mcp_knowledge_observability import render_mcp_knowledge_metrics
from ..rate_limit_state_observability import render_rate_limit_state_metrics
from . import agent_metrics, runtime_metrics
from .health_checks import evaluate_platform_health_summary, last_platform_health_checks
from .seat_allowance_metrics import seat_allowance_lines

RUN_DURATION_BUCKETS_MS = (1000, 5000, 15000, 30000, 60000, 300000, 900000)


async def render_prometheus_metrics(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_scheduler: Any,
    channel_router: Any,
    retention_worker: Any,
    outbound_webhook_worker: Any,
    connector_health_worker: Any,
    analytics_worker: Any,
    worker_monitor_worker: Any,
    worker_agenda_worker: Any,
    worker_report_worker: Any,
    worker_pool_worker: Any,
    sla_monitor_worker: Any,
    secret_expiry_worker: Any,
    session_workspace_cleanup_worker: Any,
    request_counter: Counter[tuple[str, str, str]],
) -> str:
    # The newest health run of this process (``/api/v1/health``, the probes, the API's own health loop): a scrape
    # never runs one (metrics never go through the database).
    last_health = last_platform_health_checks()
    health_checked_at, health_checks = last_health if last_health is not None else (None, {})
    health_summary = evaluate_platform_health_summary(health_checks) if health_checks else None

    lines = _request_lines(request_counter)
    lines.extend(
        [
            "# HELP connector_health Platform component health (1=ok, 0=error)",
            "# TYPE connector_health gauge",
            "# HELP octryx_queue_depth Entries waiting in the Redis task queue (worker pool autoscaling); absent"
            " without Redis",
            "# TYPE octryx_queue_depth gauge",
            *([f"octryx_queue_depth {queue_depth}"] if (queue_depth := await _redis_queue_depth(task_scheduler))
              is not None else []),
        ]
    )
    lines.extend(_health_lines(health_checks, health_summary, health_checked_at))
    lines.extend(render_mcp_knowledge_metrics())
    lines.extend(render_rate_limit_state_metrics())
    lines.extend(_agent_metric_lines())
    lines.extend(seat_allowance_lines())  # recorded where the seat answers arrive: the API
    lines.extend(_devices_online_lines())  # the device sockets live in the API process
    lines.extend(_runtime_lines())
    return "\n".join(lines) + "\n"


def _request_lines(request_counter: Counter[tuple[str, str, str]]) -> list[str]:
    lines = [
        "# HELP octryx_api_requests_total Total API requests by endpoint, method and status code",
        "# TYPE octryx_api_requests_total counter",
    ]
    for (endpoint, method, status_code), count in sorted(request_counter.items()):
        lines.append(
            f'octryx_api_requests_total{{endpoint="{endpoint}",method="{method}",status_code="{status_code}"}} {count}'
        )
    lines.extend(
        [
            "# HELP octryx_db_concurrency_events_total Database concurrency events by component and event",
            "# TYPE octryx_db_concurrency_events_total counter",
        ]
    )
    for (component, event), count in sorted(_DB_CONCURRENCY_COUNTER.items()):
        lines.append(
            f'octryx_db_concurrency_events_total{{component="{component}",event="{event}"}} {count}'
        )
    return lines


def _health_lines(
    health_checks: dict[str, dict[str, Any]], health_summary: dict[str, Any] | None, health_checked_at: float | None
) -> list[str]:
    lines: list[str] = []
    for component, payload in sorted(health_checks.items()):
        lines.append(f'connector_health{{component="{component}"}} {1 if payload["status"] == "ok" else 0}')
    lines.extend(
        [
            "# HELP octryx_platform_health_status Platform health status by aggregate state (1=current)",
            "# TYPE octryx_platform_health_status gauge",
        ]
    )
    if health_summary is not None:
        for status in ("ok", "degraded", "error"):
            current = 1 if health_summary["status"] == status else 0
            lines.append(f'octryx_platform_health_status{{status="{status}"}} {current}')
    lines.extend(
        [
            "# HELP octryx_platform_health_checked_timestamp_seconds When this process last ran its health"
            " checks (Unix seconds)",
            "# TYPE octryx_platform_health_checked_timestamp_seconds gauge",
        ]
    )
    if health_checked_at is not None:
        lines.append(f"octryx_platform_health_checked_timestamp_seconds {health_checked_at:.3f}")
    lines.extend(
        [
            "# HELP octryx_platform_component_health Platform component health by component/status (1=current)",
            "# TYPE octryx_platform_component_health gauge",
        ]
    )
    for component, payload in sorted(health_checks.items()):
        current_status = str(payload.get("status") or "unknown")
        for status in ("ok", "degraded", "error"):
            lines.append(
                f'octryx_platform_component_health{{component="{component}",status="{status}"}} '
                f"{1 if current_status == status else 0}"
            )
    return lines


async def _redis_queue_depth(task_scheduler: Any) -> int | None:
    from ...config import get_settings
    from ..redis_queue import task_queue_depth

    urls = {str(get_settings().redis_url or "").strip()}
    cached = getattr(task_scheduler, "_redis_queue_urls_cache", None)
    if isinstance(cached, tuple) and len(cached) == 3:
        urls.update(str(url).strip() for url in cached[2])
    depths = [depth for url in sorted(urls - {""}) if (depth := await task_queue_depth(url)) is not None]
    return sum(depths) if depths else None


def _agent_metric_lines() -> list[str]:
    from .sync_metrics import render as sync_lines

    return agent_metrics.render() + sync_lines()  # + the work item syncs (sync_metrics)


def _devices_online_lines() -> list[str]:
    from ..devices.hub import device_hub
    from .run_quality_metrics import online_lines

    return online_lines(device_hub)


def _runtime_lines() -> list[str]:
    from ...config import get_settings
    from ...db import core as db_core

    runtime_metrics.ensure_loop_monitor()
    return runtime_metrics.render(db_core.async_engine, app_version=get_settings().app_version)


async def render_worker_metrics(session_factory: async_sessionmaker[AsyncSession]) -> str:
    return "\n".join([*_agent_metric_lines(), *_runtime_lines()]) + "\n"
