from __future__ import annotations

from decimal import Decimal

from ...models import AgentWorker, WorkerOnboarding, WorkerRuntimeState, WorkerTrustEvent


def serialize_worker_trust_event(row: WorkerTrustEvent) -> dict[str, object]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "event_type": row.event_type,
        "task_run_id": row.task_run_id,
        "trust_delta": float(row.trust_delta or 0.0),
        "new_trust_score": float(row.new_trust_score or 0.0),
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def serialize_worker(
    worker: AgentWorker,
    *,
    serialize_time_func,
    normalize_autonomy_level_func,
    clamp_trust_score_func,
    effective_autonomy_level_func,
    can_worker_execute_action_func,
) -> dict[str, object]:
    onboarding = worker.onboarding or WorkerOnboarding(worker_id=worker.id)
    runtime = worker.runtime_state or WorkerRuntimeState(worker_id=worker.id)
    current_autonomy = effective_autonomy_level_func(worker, onboarding)
    return {
        "id": worker.id,
        "project_id": worker.project_id,
        "name": worker.name,
        "role": worker.role,
        "description": worker.description,
        "avatar_url": worker.avatar_url,
        "schedule_type": worker.schedule_type,
        "timezone": worker.timezone,
        "work_hours_start": serialize_time_func(worker.work_hours_start),
        "work_hours_end": serialize_time_func(worker.work_hours_end),
        "on_call_schedule": worker.on_call_schedule,
        "autonomy_level": normalize_autonomy_level_func(worker.autonomy_level),
        "effective_autonomy_level": current_autonomy,
        "allowed_actions": list(worker.allowed_actions or []),
        "forbidden_actions": list(worker.forbidden_actions or []),
        "report_channel": worker.report_channel,
        "escalation_user_id": worker.escalation_user_id,
        "report_schedule": worker.report_schedule,
        "trust_score": clamp_trust_score_func(worker.trust_score),
        "effective_action_permissions": {
            action: can_worker_execute_action_func(worker, onboarding, action)
            for action in ("create_ticket", "diagnose", "auto_fix")
        },
        "total_tasks_completed": int(worker.total_tasks_completed or 0),
        "total_incidents_resolved": int(worker.total_incidents_resolved or 0),
        "avg_resolution_time_minutes": worker.avg_resolution_time_minutes,
        "is_active": bool(worker.is_active),
        "created_at": worker.created_at.isoformat() if worker.created_at else None,
        "onboarding": {
            "knowledge_categories_required": list(onboarding.knowledge_categories_required or []),
            "knowledge_coverage_score": float(onboarding.knowledge_coverage_score or 0.0),
            "knowledge_gaps": list(onboarding.knowledge_gaps or []),
            "connector_checks": list(onboarding.connector_checks or []),
            "channels_verified": list(onboarding.channels_verified or []),
            "initial_autonomy_level": onboarding.initial_autonomy_level,
            "warmup_period_hours": int(onboarding.warmup_period_hours or 0),
            "onboarding_status": onboarding.onboarding_status,
            "ready_at": onboarding.ready_at.isoformat() if onboarding.ready_at else None,
        },
        "runtime_state": {
            "current_incident_id": runtime.current_incident_id,
            "current_session_id": runtime.current_session_id,
            "current_priority": runtime.current_priority,
            "active_tasks_count": int(runtime.active_tasks_count or 0),
            "max_parallel_tasks": int(runtime.max_parallel_tasks or 0),
            "available_slots": int(runtime.available_slots or 0),
            "last_k8s_check": runtime.last_k8s_check.isoformat() if runtime.last_k8s_check else None,
            "last_cost_check": runtime.last_cost_check.isoformat() if runtime.last_cost_check else None,
            "last_jira_scan": runtime.last_jira_scan.isoformat() if runtime.last_jira_scan else None,
            "system_health_summary": dict(runtime.system_health_summary or {}),
            "tasks_completed_today": int(runtime.tasks_completed_today or 0),
            "incidents_resolved_today": int(runtime.incidents_resolved_today or 0),
            "escalations_today": int(runtime.escalations_today or 0),
            "llm_cost_today": float(runtime.llm_cost_today or Decimal("0")),
            "status": runtime.status,
            "last_heartbeat": runtime.last_heartbeat.isoformat() if runtime.last_heartbeat else None,
            "updated_at": runtime.updated_at.isoformat() if runtime.updated_at else None,
        },
    }
