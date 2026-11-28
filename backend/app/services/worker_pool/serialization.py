"""Serialization helpers for worker pool APIs."""

from typing import Any

from ...models import (
    TaskRoutingRule,
    WorkerCapacityLog,
    WorkerDomainExpertise,
    WorkerPoolConfig,
    WorkerRateLimit,
)


def serialize_pool_config(row: WorkerPoolConfig) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "min_workers": int(row.min_workers or 1),
        "max_workers": int(row.max_workers or 10),
        "current_workers": int(row.current_workers or 1),
        "scale_up_threshold": int(row.scale_up_threshold or 5),
        "scale_down_threshold": int(row.scale_down_threshold or 1),
        "scale_up_cooldown_minutes": int(row.scale_up_cooldown_minutes or 5),
        "scale_down_cooldown_minutes": int(row.scale_down_cooldown_minutes or 15),
        "max_llm_cost_per_hour": float(row.max_llm_cost_per_hour or 0),
        "last_scale_action": row.last_scale_action,
        "last_scale_at": row.last_scale_at.isoformat() if row.last_scale_at else None,
        "queue_backend": row.queue_backend,
        "redis_url": row.redis_url,
        "hpa_target_queue_depth": int(row.hpa_target_queue_depth or 5),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_worker_rate_limit(row: WorkerRateLimit) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "max_requests_per_minute": int(row.max_requests_per_minute or 60),
        "max_tokens_per_hour": int(row.max_tokens_per_hour or 500000),
        "max_cost_per_hour": float(row.max_cost_per_hour or 0),
        "max_cost_per_day": float(row.max_cost_per_day or 0),
        "on_minute_limit": row.on_minute_limit,
        "on_cost_limit": row.on_cost_limit,
        "current_rpm": float(row.current_rpm or 0),
        "current_hour_tokens": int(row.current_hour_tokens or 0),
        "current_hour_cost": float(row.current_hour_cost or 0),
        "current_day_cost": float(row.current_day_cost or 0),
        "reset_minute_at": row.reset_minute_at.isoformat() if row.reset_minute_at else None,
        "reset_hour_at": row.reset_hour_at.isoformat() if row.reset_hour_at else None,
        "reset_day_at": row.reset_day_at.isoformat() if row.reset_day_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_domain_expertise(row: WorkerDomainExpertise) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "domain": row.domain,
        "expertise_level": row.expertise_level,
        "tasks_completed": int(row.tasks_completed or 0),
        "avg_resolution_time_minutes": row.avg_resolution_time_minutes,
        "success_rate": float(row.success_rate or 0.0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_capacity_log(row: WorkerCapacityLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "queue_depth": int(row.queue_depth or 0),
        "active_tasks": int(row.active_tasks or 0),
        "avg_task_duration_minutes": row.avg_task_duration_minutes,
        "llm_cost_last_hour": float(row.llm_cost_last_hour or 0),
        "cpu_pressure": row.cpu_pressure,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    }


def serialize_routing_rule(row: TaskRoutingRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "priority": int(row.priority or 100),
        "condition_type": row.condition_type,
        "condition_config": dict(row.condition_config or {}),
        "target_type": row.target_type,
        "target_config": dict(row.target_config or {}),
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
