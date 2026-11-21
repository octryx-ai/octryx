from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentWorker,
    Project,
    Session,
    TaskRun,
    User,
    WorkerOnboarding,
    WorkerRuntimeState,
    WorkerTrustEvent,
)
from ...time_utils import utc_now
from ..connector_test_service import run_connector_connection_test
from ..system_config import get_worker_trust_deltas
from ..tool_config import TOOL_CONFIG_PRESETS
from .admin import get_worker_with_relations, require_admin
from .policy import (
    CRITICAL_CONNECTORS,
    DEFAULT_WORKER_KNOWLEDGE_CATEGORIES,
    can_worker_execute_action,
    clamp_trust_score,
    effective_autonomy_level,
    minimum_trust_for_autonomy,
    normalize_autonomy_level,
    normalize_string_list,
    parse_time,
    serialize_time,
    sync_worker_autonomy_from_trust,
)
from .readiness import refresh_all_workers_on_startup as refresh_all_workers_on_startup_impl
from .readiness import refresh_worker_startup_state as refresh_worker_startup_state_impl
from .serialization import serialize_worker as serialize_worker_impl
from .serialization import serialize_worker_trust_event as serialize_worker_trust_event_impl


def serialize_worker_trust_event(row: WorkerTrustEvent) -> dict[str, object]:
    return serialize_worker_trust_event_impl(row)


async def serialize_worker(worker: AgentWorker) -> dict[str, object]:
    return await serialize_worker_impl(
        worker,
        serialize_time_func=serialize_time,
        normalize_autonomy_level_func=normalize_autonomy_level,
        clamp_trust_score_func=clamp_trust_score,
        effective_autonomy_level_func=effective_autonomy_level,
        can_worker_execute_action_func=can_worker_execute_action,
    )


async def refresh_worker_startup_state(
    db: AsyncSession,
    worker: AgentWorker,
    *,
    connector_test_func=None,
) -> AgentWorker:
    # Resolve the connector test at call time so tests can monkeypatch
    # `run_connector_connection_test` on this module.
    return await refresh_worker_startup_state_impl(
        db,
        worker,
        connector_test_func=connector_test_func or run_connector_connection_test,
        tool_config_presets=TOOL_CONFIG_PRESETS,
        default_worker_knowledge_categories=DEFAULT_WORKER_KNOWLEDGE_CATEGORIES,
        critical_connectors=CRITICAL_CONNECTORS,
        normalize_string_list_func=normalize_string_list,
        sync_worker_autonomy_from_trust_func=sync_worker_autonomy_from_trust,
        utc_now_func=utc_now,
    )


async def refresh_all_workers_on_startup(
    db: AsyncSession,
    *,
    refresh_worker_startup_state_func=None,
) -> int:
    return await refresh_all_workers_on_startup_impl(
        db,
        refresh_worker_startup_state_func=refresh_worker_startup_state_func or refresh_worker_startup_state,
    )


async def list_workers(db: AsyncSession, current_user: User) -> list[dict[str, object]]:
    await require_admin(db, current_user)
    workers = (
        (
            await db.execute(
                select(AgentWorker)
                .options(
                    selectinload(AgentWorker.onboarding),
                    selectinload(AgentWorker.runtime_state),
                    selectinload(AgentWorker.trust_events),
                )
                .order_by(AgentWorker.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [await serialize_worker(worker) for worker in workers]


async def create_worker(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
    refresh_worker_startup_state_func=None,
) -> dict[str, object]:
    await require_admin(db, current_user)
    project = await db.get(Project, payload["project_id"])
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    escalation_user_id = payload.get("escalation_user_id")
    if escalation_user_id and not await db.get(User, escalation_user_id):
        raise HTTPException(status_code=404, detail="Escalation user not found")
    worker = AgentWorker(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=str(payload["name"]).strip(),
        role=str(payload["role"]).strip(),
        description=(payload.get("description") or "").strip() or None,
        avatar_url=(payload.get("avatar_url") or "").strip() or None,
        schedule_type=str(payload.get("schedule_type") or "always_on").strip(),
        timezone=str(payload.get("timezone") or "UTC").strip(),
        work_hours_start=parse_time(payload.get("work_hours_start")),
        work_hours_end=parse_time(payload.get("work_hours_end")),
        on_call_schedule=payload.get("on_call_schedule") or {},
        autonomy_level=normalize_autonomy_level(payload.get("autonomy_level") or "supervised"),
        allowed_actions=normalize_string_list(payload.get("allowed_actions")),
        forbidden_actions=normalize_string_list(payload.get("forbidden_actions")),
        report_channel=(payload.get("report_channel") or "").strip() or None,
        escalation_user_id=escalation_user_id,
        report_schedule=(payload.get("report_schedule") or "").strip() or None,
        trust_score=clamp_trust_score(payload.get("trust_score") or 0.5),
    )
    if payload.get("trust_score") is None and payload.get("autonomy_level") is not None:
        worker.trust_score = minimum_trust_for_autonomy(worker.autonomy_level)
    onboarding = WorkerOnboarding(
        worker_id=worker.id,
        knowledge_categories_required=normalize_string_list(payload.get("knowledge_categories_required"))
        or list(DEFAULT_WORKER_KNOWLEDGE_CATEGORIES),
        initial_autonomy_level=worker.autonomy_level,
        warmup_period_hours=int(payload.get("warmup_period_hours") or 24),
        onboarding_status="pending",
    )
    runtime = WorkerRuntimeState(
        worker_id=worker.id,
        current_priority="idle",
        active_tasks_count=0,
        max_parallel_tasks=int(payload.get("max_parallel_tasks") or 3),
        available_slots=int(payload.get("max_parallel_tasks") or 3),
        system_health_summary={},
        status="active" if worker.is_active else "paused",
        last_heartbeat=utc_now(),
    )
    worker.onboarding = onboarding
    worker.runtime_state = runtime
    sync_worker_autonomy_from_trust(worker)
    db.add(worker)
    await db.flush()
    startup_refresh = refresh_worker_startup_state_func or refresh_worker_startup_state
    await startup_refresh(db, worker)
    await db.commit()
    reloaded = await get_worker_with_relations(db, worker.id)
    if reloaded is None:
        raise HTTPException(status_code=500, detail="Worker could not be reloaded after creation")
    return await serialize_worker(reloaded)


async def patch_worker(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    payload: dict[str, Any],
    refresh_worker_startup_state_func=None,
) -> dict[str, object]:
    await require_admin(db, current_user)
    worker = await get_worker_with_relations(db, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    onboarding = worker.onboarding or WorkerOnboarding(worker_id=worker.id)
    runtime = worker.runtime_state or WorkerRuntimeState(worker_id=worker.id)
    if worker.onboarding is None:
        db.add(onboarding)
        worker.onboarding = onboarding
    if worker.runtime_state is None:
        db.add(runtime)
        worker.runtime_state = runtime

    mutable_text_fields = (
        "name",
        "role",
        "description",
        "avatar_url",
        "schedule_type",
        "timezone",
        "report_channel",
        "report_schedule",
    )
    nullable_text_fields = {"description", "avatar_url", "report_channel", "report_schedule"}
    for field in mutable_text_fields:
        if field in payload and payload[field] is not None:
            stripped = str(payload[field]).strip()
            setattr(worker, field, (stripped or None) if field in nullable_text_fields else stripped)
    if "work_hours_start" in payload:
        worker.work_hours_start = parse_time(payload.get("work_hours_start"))
    if "work_hours_end" in payload:
        worker.work_hours_end = parse_time(payload.get("work_hours_end"))
    if "on_call_schedule" in payload and payload.get("on_call_schedule") is not None:
        worker.on_call_schedule = payload.get("on_call_schedule")
    if "autonomy_level" in payload and payload.get("autonomy_level") is not None:
        worker.autonomy_level = normalize_autonomy_level(payload["autonomy_level"])
        if payload.get("trust_score") is None:
            worker.trust_score = minimum_trust_for_autonomy(worker.autonomy_level)
    if "allowed_actions" in payload and payload.get("allowed_actions") is not None:
        worker.allowed_actions = normalize_string_list(payload.get("allowed_actions"))
    if "forbidden_actions" in payload and payload.get("forbidden_actions") is not None:
        worker.forbidden_actions = normalize_string_list(payload.get("forbidden_actions"))
    if "trust_score" in payload and payload.get("trust_score") is not None:
        worker.trust_score = clamp_trust_score(payload["trust_score"])
        sync_worker_autonomy_from_trust(worker)
    if "is_active" in payload and payload.get("is_active") is not None:
        worker.is_active = bool(payload["is_active"])
    if "escalation_user_id" in payload:
        escalation_user_id = payload.get("escalation_user_id")
        if escalation_user_id and not await db.get(User, escalation_user_id):
            raise HTTPException(status_code=404, detail="Escalation user not found")
        worker.escalation_user_id = escalation_user_id
    if "knowledge_categories_required" in payload and payload.get("knowledge_categories_required") is not None:
        onboarding.knowledge_categories_required = normalize_string_list(payload["knowledge_categories_required"])
    if "warmup_period_hours" in payload and payload.get("warmup_period_hours") is not None:
        onboarding.warmup_period_hours = int(payload["warmup_period_hours"])

    for field in ("current_incident_id", "current_session_id", "current_priority", "status"):
        if field in payload and payload.get(field) is not None:
            setattr(runtime, field, str(payload[field]).strip())
    for field in (
        "active_tasks_count",
        "max_parallel_tasks",
        "tasks_completed_today",
        "incidents_resolved_today",
        "escalations_today",
    ):
        if field in payload and payload.get(field) is not None:
            setattr(runtime, field, int(payload[field]))
    if "llm_cost_today" in payload and payload.get("llm_cost_today") is not None:
        runtime.llm_cost_today = Decimal(str(payload["llm_cost_today"]))
    if "system_health_summary" in payload and payload.get("system_health_summary") is not None:
        runtime.system_health_summary = dict(payload["system_health_summary"])
    if payload.get("heartbeat"):
        runtime.last_heartbeat = utc_now()
    if runtime.current_session_id and not await db.get(Session, runtime.current_session_id):
        raise HTTPException(status_code=404, detail="Current session not found")

    startup_refresh = refresh_worker_startup_state_func or refresh_worker_startup_state
    await startup_refresh(db, worker)
    await db.commit()
    reloaded = await get_worker_with_relations(db, worker.id)
    if reloaded is None:
        raise HTTPException(status_code=500, detail="Worker could not be reloaded after update")
    return await serialize_worker(reloaded)


async def list_worker_trust_events(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    limit: int = 50,
) -> list[dict[str, object]]:
    await require_admin(db, current_user)
    worker = await get_worker_with_relations(db, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    rows = (
        (
            await db.execute(
                select(WorkerTrustEvent)
                .where(WorkerTrustEvent.worker_id == worker_id)
                .order_by(WorkerTrustEvent.created_at.desc())
                .limit(max(1, min(int(limit), 200)))
            )
        )
        .scalars()
        .all()
    )
    return [serialize_worker_trust_event(row) for row in rows]


async def create_worker_trust_event(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    payload: dict[str, Any],
    record_worker_trust_event_func=None,
) -> dict[str, object]:
    await require_admin(db, current_user)
    worker = await get_worker_with_relations(db, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    trust_event_recorder = record_worker_trust_event_func or record_worker_trust_event
    return await trust_event_recorder(
        db,
        worker=worker,
        event_type=str(payload["event_type"]).strip(),
        task_run_id=payload.get("task_run_id"),
        reason=(payload.get("reason") or "").strip() or None,
        explicit_delta=payload.get("trust_delta"),
    )


async def record_worker_trust_event(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    event_type: str,
    task_run_id: str | None = None,
    reason: str | None = None,
    explicit_delta: float | None = None,
    get_worker_trust_deltas_func=get_worker_trust_deltas,
) -> dict[str, object]:
    normalized_event_type = str(event_type or "").strip().lower()
    configured_trust_deltas = await get_worker_trust_deltas_func(db)
    if normalized_event_type not in configured_trust_deltas and explicit_delta is None:
        raise HTTPException(status_code=422, detail=f"Unsupported worker trust event '{normalized_event_type}'")
    if task_run_id and not await db.get(TaskRun, task_run_id):
        raise HTTPException(status_code=404, detail="Task run not found")
    delta = float(explicit_delta if explicit_delta is not None else configured_trust_deltas[normalized_event_type])
    worker.trust_score = clamp_trust_score(float(worker.trust_score or 0.0) + delta)
    sync_worker_autonomy_from_trust(worker)
    if normalized_event_type == "success":
        worker.total_tasks_completed = int(worker.total_tasks_completed or 0) + 1
    event = WorkerTrustEvent(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        event_type=normalized_event_type,
        task_run_id=task_run_id,
        trust_delta=delta,
        new_trust_score=worker.trust_score,
        reason=reason,
    )
    db.add(event)
    await db.flush()
    return serialize_worker_trust_event(event)
