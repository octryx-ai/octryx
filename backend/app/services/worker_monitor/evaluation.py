from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...models import (
    AgentWorker,
    ConnectorHealth,
    PolicyDecisionLog,
    Session,
    ToolCall,
    UsageEvent,
    WorkerMonitor,
    WorkerMonitorEvent,
)
from ...time_utils import utc_now, utc_now_aware
from ..decisions.recorder import GATE_CONTENT_SECURITY

MonitorActionApplier = Callable[..., Awaitable[tuple[str | None, str | None]]]


def _numeric_thresholds(threshold_config: dict[str, Any]) -> tuple[float | None, float | None]:
    warning = threshold_config.get("warning")
    critical = threshold_config.get("critical")
    return (float(warning) if warning is not None else None, float(critical) if critical is not None else None)


# Usage and tool calls carry no Workspace of their own: they belong to the Workspace of their
# session. (Filtering on a `project_id` column of these tables crashed the cost, log and security monitors.)
async def _workspace_cost(db: AsyncSession, project_id: str | None, start: datetime, end: datetime) -> float:
    stmt = (
        select(func.coalesce(func.sum(UsageEvent.cost), 0))
        .join(Session, Session.id == UsageEvent.session_id)
        .where(Session.project_id == project_id, UsageEvent.created_at >= start, UsageEvent.created_at < end)
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _workspace_count(db: AsyncSession, model: Any, project_id: str | None, *conditions: Any) -> float:
    stmt = (
        select(func.count(model.id))
        .join(Session, Session.id == model.session_id)
        .where(Session.project_id == project_id, *conditions)
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _evaluate_monitor_value(
    db: AsyncSession, worker: AgentWorker, monitor: WorkerMonitor
) -> tuple[str, str, str, dict[str, Any]]:
    threshold_config = dict(monitor.threshold_config or {})
    baseline = dict(monitor.baseline_json or {})
    sample_value = threshold_config.get("sample_value", baseline.get("sample_value"))
    sample_count = threshold_config.get("sample_count", baseline.get("sample_count"))

    if sample_value is not None or sample_count is not None:
        numeric_value = float(sample_value if sample_value is not None else sample_count)
    elif monitor.monitor_type == "k8s_health":
        runtime_summary = dict((worker.runtime_state.system_health_summary if worker.runtime_state else {}) or {})
        connector_row = (
            (
                await db.execute(
                    select(ConnectorHealth)
                    .where(
                        ConnectorHealth.connector_name == "kubernetes",
                        or_(ConnectorHealth.project_id == worker.project_id, ConnectorHealth.project_id.is_(None)),
                    )
                    .order_by(ConnectorHealth.checked_at.desc())
                )
            )
            .scalars()
            .first()
        )
        status_label = str(runtime_summary.get("k8s") or getattr(connector_row, "status", "ok") or "ok").lower()
        numeric_value = {"ok": 0.0, "degraded": 1.0, "warning": 1.0, "error": 2.0, "failed": 2.0}.get(status_label, 0.0)
        baseline["status_label"] = status_label
    elif monitor.monitor_type == "cost_anomaly":
        now = utc_now()
        current_cutoff = now - timedelta(hours=24)
        previous_cutoff = now - timedelta(hours=48)
        current_total = await _workspace_cost(db, worker.project_id, current_cutoff, now)
        previous_total = await _workspace_cost(db, worker.project_id, previous_cutoff, current_cutoff)
        numeric_value = 0.0 if previous_total <= 0 else ((current_total - previous_total) / previous_total) * 100.0
        baseline["current_total_cost"] = round(current_total, 4)
        baseline["previous_total_cost"] = round(previous_total, 4)
    elif monitor.monitor_type == "log_error_pattern":
        lookback_minutes = int(threshold_config.get("lookback_minutes") or 60)
        cutoff = utc_now() - timedelta(minutes=lookback_minutes)
        numeric_value = await _workspace_count(
            db, ToolCall, worker.project_id, ToolCall.created_at >= cutoff, ToolCall.status == "error"
        )
    elif monitor.monitor_type == "security_alert":
        lookback_minutes = int(threshold_config.get("lookback_minutes") or 1440)
        cutoff = utc_now() - timedelta(minutes=lookback_minutes)
        # The shipped content policies' decisions (refused, masked, reported) in the Workspace.
        numeric_value = float((await db.execute(select(func.count(PolicyDecisionLog.id)).where(
            PolicyDecisionLog.gate == GATE_CONTENT_SECURITY, PolicyDecisionLog.workspace_id == worker.project_id,
            PolicyDecisionLog.created_at >= cutoff,
        ))).scalar() or 0)
    else:
        numeric_value = 0.0

    warning_threshold, critical_threshold = _numeric_thresholds(threshold_config)
    severity = "ok"
    if critical_threshold is not None and numeric_value >= critical_threshold:
        severity = "critical"
    elif warning_threshold is not None and numeric_value >= warning_threshold:
        severity = "warning"
    elif numeric_value > 0:
        severity = "warning"

    detected_value = str(round(numeric_value, 4))
    threshold_value = f"warning={warning_threshold}, critical={critical_threshold}"
    baseline["last_value"] = numeric_value
    baseline["last_evaluated_at"] = utc_now_aware().isoformat()
    return severity, detected_value, threshold_value, baseline


async def _resolve_open_events(db: AsyncSession, monitor: WorkerMonitor, summary: str) -> None:
    rows = (
        (
            await db.execute(
                select(WorkerMonitorEvent).where(
                    WorkerMonitorEvent.monitor_id == monitor.id,
                    WorkerMonitorEvent.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    now = utc_now()
    for row in rows:
        row.resolved_at = now
        row.resolution_summary = summary


async def evaluate_worker_monitor(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    worker: AgentWorker,
    monitor: WorkerMonitor,
    apply_monitor_action: MonitorActionApplier,
) -> dict[str, Any]:
    severity, detected_value, threshold_value, new_baseline = await _evaluate_monitor_value(db, worker, monitor)
    previous_status = str(monitor.last_status or "unknown").lower()
    changed = severity != previous_status
    monitor.last_check_at = utc_now()
    monitor.last_status = severity
    monitor.baseline_json = new_baseline
    monitor.consecutive_failures = 0 if severity == "ok" else int(monitor.consecutive_failures or 0) + 1

    if severity == "ok":
        await _resolve_open_events(db, monitor, f"Recovered to ok with value {detected_value}")
        await db.flush()
        return {"status": "ok", "severity": severity, "event": None}

    if not changed:
        await db.flush()
        return {"status": "unchanged", "severity": severity, "event": None}

    action = monitor.action_on_critical if severity == "critical" else monitor.action_on_warning
    session_id, resolved_action = await apply_monitor_action(
        db,
        session_factory,
        worker=worker,
        monitor=monitor,
        severity=severity,
        detected_value=detected_value,
        action=action,
    )
    event = WorkerMonitorEvent(
        id=str(uuid.uuid4()),
        monitor_id=monitor.id,
        worker_id=worker.id,
        severity=severity,
        detected_value=detected_value,
        threshold_value=threshold_value,
        triggered_action=resolved_action,
        session_id=session_id,
    )
    db.add(event)
    if worker.runtime_state:
        worker.runtime_state.current_priority = severity
        worker.runtime_state.system_health_summary = {
            **dict(worker.runtime_state.system_health_summary or {}),
            monitor.monitor_type: severity,
        }
    await db.flush()
    return {"status": "triggered", "severity": severity, "event": event}
