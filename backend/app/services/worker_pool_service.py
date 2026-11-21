from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.worker_pool.dispatch import ROUTING_CONDITION_TYPES
from app.services.worker_pool.scaling import (
    build_project_worker_manifests as _build_project_worker_manifests,
)
from app.services.worker_pool.scaling import (
    evaluate_pool_scaling as _evaluate_pool_scaling,
)
from app.services.worker_pool.serialization import (
    serialize_capacity_log,
    serialize_domain_expertise,
    serialize_pool_config,
    serialize_routing_rule,
    serialize_worker_rate_limit,
)
from app.services.worker_pool.state import (
    _refresh_rate_limit_usage,
    get_or_create_worker_pool_config,
    get_or_create_worker_rate_limit,
    mark_worker_pool_config_changed,
    update_worker_domain_expertise,
)

from ..models import Project, TaskRoutingRule, WorkerCapacityLog, WorkerDomainExpertise
from .worker.admin import require_admin as _require_admin

logger = logging.getLogger(__name__)


async def get_pool_config(db: AsyncSession, *, project_id: str, current_user) -> dict[str, Any]:
    await _require_admin(db, current_user)
    return serialize_pool_config(await get_or_create_worker_pool_config(db, project_id))


async def update_pool_config(
    db: AsyncSession, *, project_id: str, current_user, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await get_or_create_worker_pool_config(db, project_id)
    for field in (
        "min_workers",
        "max_workers",
        "current_workers",
        "scale_up_threshold",
        "scale_down_threshold",
        "scale_up_cooldown_minutes",
        "scale_down_cooldown_minutes",
        "hpa_target_queue_depth",
    ):
        if field in payload and payload[field] is not None:
            setattr(row, field, int(payload[field]))
    for field in ("queue_backend", "redis_url", "last_scale_action"):
        if field in payload:
            setattr(row, field, payload[field])
    if "max_llm_cost_per_hour" in payload and payload["max_llm_cost_per_hour"] is not None:
        row.max_llm_cost_per_hour = Decimal(str(payload["max_llm_cost_per_hour"]))
    if row.current_workers < row.min_workers:
        row.current_workers = row.min_workers
    if row.current_workers > row.max_workers:
        row.current_workers = row.max_workers
    await db.commit()
    mark_worker_pool_config_changed()
    await db.refresh(row)
    return serialize_pool_config(row)


async def get_project_rate_limit(db: AsyncSession, *, project_id: str, current_user) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await get_or_create_worker_rate_limit(db, project_id)
    await _refresh_rate_limit_usage(db, row)
    await db.commit()
    return serialize_worker_rate_limit(row)


async def update_project_rate_limit(
    db: AsyncSession, *, project_id: str, current_user, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await get_or_create_worker_rate_limit(db, project_id)
    for field in ("max_requests_per_minute", "max_tokens_per_hour"):
        if field in payload and payload[field] is not None:
            setattr(row, field, int(payload[field]))
    for field in ("on_minute_limit", "on_cost_limit"):
        if field in payload and payload[field]:
            setattr(row, field, str(payload[field]).strip())
    for field in ("max_cost_per_hour", "max_cost_per_day"):
        if field in payload and payload[field] is not None:
            setattr(row, field, Decimal(str(payload[field])))
    await _refresh_rate_limit_usage(db, row)
    await db.commit()
    await db.refresh(row)
    return serialize_worker_rate_limit(row)


async def list_worker_capacity_logs(
    db: AsyncSession, *, worker_id: str, current_user, limit: int = 20
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    rows = (
        (
            await db.execute(
                select(WorkerCapacityLog)
                .where(WorkerCapacityLog.worker_id == worker_id)
                .order_by(WorkerCapacityLog.recorded_at.desc())
                .limit(max(1, min(int(limit), 100)))
            )
        )
        .scalars()
        .all()
    )
    return [serialize_capacity_log(row) for row in rows]


async def list_worker_domain_expertise(db: AsyncSession, *, worker_id: str, current_user) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    rows = (
        (
            await db.execute(
                select(WorkerDomainExpertise)
                .where(WorkerDomainExpertise.worker_id == worker_id)
                .order_by(WorkerDomainExpertise.domain.asc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_domain_expertise(row) for row in rows]


async def upsert_worker_domain_expertise(
    db: AsyncSession, *, worker_id: str, current_user, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await update_worker_domain_expertise(
        db,
        worker_id=worker_id,
        domain=str(payload.get("domain") or "any"),
        success=bool(payload.get("success", True)),
        duration_minutes=(float(payload["duration_minutes"]) if payload.get("duration_minutes") is not None else None),
    )
    if row is None:
        raise HTTPException(status_code=422, detail="domain is required")
    await db.commit()
    await db.refresh(row)
    return serialize_domain_expertise(row)


async def list_task_routing_rules(db: AsyncSession, *, project_id: str, current_user) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    rows = (
        (
            await db.execute(
                select(TaskRoutingRule)
                .where(TaskRoutingRule.project_id == project_id)
                .order_by(TaskRoutingRule.priority.asc(), TaskRoutingRule.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_routing_rule(row) for row in rows]


async def create_task_routing_rule(
    db: AsyncSession, *, project_id: str, current_user, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    condition_type = str(payload.get("condition_type") or "").strip()
    if condition_type not in ROUTING_CONDITION_TYPES:
        raise HTTPException(
            status_code=422, detail=f"condition_type must be one of: {', '.join(ROUTING_CONDITION_TYPES)}."
        )
    row = TaskRoutingRule(
        id=str(uuid.uuid4()),
        project_id=project_id,
        priority=int(payload.get("priority") or 100),
        condition_type=condition_type,
        condition_config=payload.get("condition_config") or {},
        target_type=str(payload.get("target_type") or "worker_pool").strip(),
        target_config=payload.get("target_config") or {},
        is_active=1 if payload.get("is_active", True) else 0,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize_routing_rule(row)


async def evaluate_pool_scaling(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    return await _evaluate_pool_scaling(db, project_id=project_id)


async def build_project_worker_manifests(db: AsyncSession, *, project_id: str, current_user) -> dict[str, Any]:
    return await _build_project_worker_manifests(
        db,
        project_id=project_id,
        current_user=current_user,
        require_admin=_require_admin,
    )


__all__ = [
    "get_pool_config",
    "update_pool_config",
    "get_project_rate_limit",
    "update_project_rate_limit",
    "list_worker_capacity_logs",
    "list_worker_domain_expertise",
    "upsert_worker_domain_expertise",
    "list_task_routing_rules",
    "create_task_routing_rule",
    "evaluate_pool_scaling",
    "build_project_worker_manifests",
]
