from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SLABreach, SLADefinition, Task, User
from ..admin.governance.admin_access_service import is_global_admin

ALLOWED_BREACH_TYPES = {"warning_threshold", "duration_exceeded"}


def serialize_sla_definition(row: SLADefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "task_id": row.task_id,
        "agent_type": row.agent_type,
        "max_duration_seconds": int(row.max_duration_seconds or 0),
        "alert_threshold": float(row.alert_threshold or 0.0),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_sla_breach(row: SLABreach) -> dict[str, Any]:
    return {
        "id": row.id,
        "sla_definition_id": row.sla_definition_id,
        "task_run_id": row.task_run_id,
        "task_id": row.task_id,
        "expected_at": row.expected_at.isoformat() if row.expected_at else None,
        "actual_at": row.actual_at.isoformat() if row.actual_at else None,
        "breach_type": row.breach_type,
        "severity": row.severity,
        "is_resolved": bool(row.is_resolved),
        "notification_sent": bool(row.notification_sent),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


async def require_admin(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")


def _normalize_threshold(value: Any) -> float:
    threshold = float(value if value is not None else 0.8)
    if threshold <= 0 or threshold > 1:
        raise HTTPException(status_code=422, detail="alert_threshold must be between 0 and 1")
    return threshold


async def _validate_task_id(db: AsyncSession, task_id: str | None) -> str | None:
    if not task_id:
        return None
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.id


def _normalize_agent_type(agent_type: Any) -> str | None:
    text = str(agent_type or "").strip()
    return text or None


def build_sla_definition(*, payload: dict[str, Any], task_id: str | None, agent_type: str | None) -> SLADefinition:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if not task_id and not agent_type:
        raise HTTPException(status_code=422, detail="task_id or agent_type is required")
    max_duration_seconds = int(payload.get("max_duration_seconds") or 0)
    if max_duration_seconds <= 0:
        raise HTTPException(status_code=422, detail="max_duration_seconds must be greater than 0")
    return SLADefinition(
        id=str(uuid.uuid4()),
        name=name,
        task_id=task_id,
        agent_type=agent_type,
        max_duration_seconds=max_duration_seconds,
        alert_threshold=_normalize_threshold(payload.get("alert_threshold")),
        is_active=bool(payload.get("is_active", True)),
    )
