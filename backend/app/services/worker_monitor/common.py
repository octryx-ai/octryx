from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentWorker, User, WorkerMonitor, WorkerMonitorEvent
from ..admin.governance.admin_access_service import is_global_admin
from ..notification_delivery.access import user_role_names

ALLOWED_MONITOR_TYPES = {
    "k8s_health",
    "prometheus_query",
    "jira_backlog",
    "cost_anomaly",
    "log_error_pattern",
    "security_alert",
}
ALLOWED_MONITOR_ACTIONS = {"log", "notify", "create_ticket", "diagnose", "auto_fix", "escalate", "page"}


def _normalize_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_action(value: Any) -> str | None:
    action = _normalize_string(value)
    if action is None:
        return None
    action = action.lower()
    if action not in ALLOWED_MONITOR_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported worker monitor action '{action}'")
    return action


def _normalize_monitor_type(value: Any) -> str:
    monitor_type = str(value or "").strip().lower()
    if monitor_type not in ALLOWED_MONITOR_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported worker monitor type '{monitor_type}'")
    return monitor_type


async def _require_admin(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")


async def _user_role_names(db: AsyncSession, user_id: str) -> set[str]:
    return await user_role_names(db, user_id)


async def _get_worker(db: AsyncSession, worker_id: str) -> AgentWorker:
    worker = (
        await db.execute(
            select(AgentWorker)
            .options(selectinload(AgentWorker.runtime_state), selectinload(AgentWorker.onboarding))
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


async def _get_monitor(db: AsyncSession, worker_id: str, monitor_id: str) -> WorkerMonitor:
    monitor = (
        await db.execute(
            select(WorkerMonitor)
            .options(selectinload(WorkerMonitor.events))
            .where(WorkerMonitor.worker_id == worker_id, WorkerMonitor.id == monitor_id)
        )
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=404, detail="Worker monitor not found")
    return monitor


def serialize_worker_monitor(row: WorkerMonitor) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "name": row.name,
        "monitor_type": row.monitor_type,
        "check_interval_minutes": int(row.check_interval_minutes or 0),
        "check_query": row.check_query,
        "threshold_config": dict(row.threshold_config or {}),
        "action_on_warning": row.action_on_warning,
        "action_on_critical": row.action_on_critical,
        "baseline_json": dict(row.baseline_json or {}),
        "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
        "last_status": row.last_status,
        "consecutive_failures": int(row.consecutive_failures or 0),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_worker_monitor_event(row: WorkerMonitorEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "monitor_id": row.monitor_id,
        "worker_id": row.worker_id,
        "severity": row.severity,
        "detected_value": row.detected_value,
        "threshold_value": row.threshold_value,
        "triggered_action": row.triggered_action,
        "session_id": row.session_id,
        "task_run_id": row.task_run_id,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolution_summary": row.resolution_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
