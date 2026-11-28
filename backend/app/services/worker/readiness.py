from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentWorker,
    ChannelConfig,
    Project,
    WorkerOnboarding,
    WorkerRuntimeState,
)
from ..project.service import get_project_config
from ..tool_config import list_tool_configs


async def project_connector_checks(
    project: Project,
    *,
    tool_config_presets: dict[str, dict[str, Any]],
    connector_test_func,
    db: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    if db is None:
        return []
    config = await get_project_config(project.id, db)
    entries = {entry.tool_name for entry in await list_tool_configs(db, project.id) if entry.is_active}
    checks: list[dict[str, Any]] = []
    for connector_name, preset in tool_config_presets.items():
        fields = preset.get("fields") or []
        if connector_name not in entries or not any(config.get(field) not in (None, "", [], {}) for field in fields):
            continue
        result = await connector_test_func(
            connector_name,
            {field: config.get(field) for field in fields if config.get(field) not in (None, "", [], {})},
        )
        checks.append(
            {
                "connector": connector_name,
                "status": "ok" if result.get("ok") else "failed",
                "summary": result.get("summary"),
                "details": result.get("details"),
            }
        )
    return checks


async def verify_channels(db: AsyncSession, worker: AgentWorker) -> list[dict[str, Any]]:
    report_channel = str(worker.report_channel or "").strip()
    if not report_channel:
        return []
    rows = (
        (
            await db.execute(
                select(ChannelConfig).where(
                    ChannelConfig.enabled.is_(True),
                    (ChannelConfig.project_id == worker.project_id) | (ChannelConfig.project_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    channel_status = "ok" if rows or report_channel else "missing"
    return [
        {
            "channel": report_channel,
            "status": channel_status,
            "matched_configs": [row.plugin_id for row in rows],
        }
    ]


async def refresh_worker_startup_state(
    db: AsyncSession,
    worker: AgentWorker,
    *,
    connector_test_func,
    tool_config_presets: dict[str, dict[str, Any]],
    default_worker_knowledge_categories: list[str],
    critical_connectors: tuple[str, ...],
    normalize_string_list_func,
    sync_worker_autonomy_from_trust_func,
    utc_now_func,
) -> AgentWorker:
    onboarding = worker.onboarding or WorkerOnboarding(worker_id=worker.id)
    runtime = worker.runtime_state or WorkerRuntimeState(worker_id=worker.id)
    if worker.onboarding is None:
        db.add(onboarding)
        worker.onboarding = onboarding
    if worker.runtime_state is None:
        db.add(runtime)
        worker.runtime_state = runtime

    required_categories = normalize_string_list_func(
        onboarding.knowledge_categories_required or default_worker_knowledge_categories
    )
    if not required_categories:
        required_categories = list(default_worker_knowledge_categories)
    onboarding.knowledge_categories_required = required_categories
    sync_worker_autonomy_from_trust_func(worker)
    onboarding.initial_autonomy_level = onboarding.initial_autonomy_level or worker.autonomy_level

    # No governed source maps onto the required categories yet. Coverage is therefore not assumed: every
    # required category is an open gap, so the worker stays supervised until an explicit knowledge
    # readiness source exists (open product decision). There is no fallback that relaxes the gate.
    onboarding.knowledge_coverage_score = 0.0
    onboarding.knowledge_gaps = list(required_categories)

    project = await db.get(Project, worker.project_id)
    onboarding.connector_checks = (
        await project_connector_checks(
            project,
            tool_config_presets=tool_config_presets,
            connector_test_func=connector_test_func,
            db=db,
        )
        if project
        else []
    )
    onboarding.channels_verified = await verify_channels(db, worker)

    critical_checks = [item for item in onboarding.connector_checks if item.get("connector") in critical_connectors]
    critical_ok = all(item.get("status") == "ok" for item in critical_checks)
    channels_ok = any(item.get("status") == "ok" for item in onboarding.channels_verified)
    ready = onboarding.knowledge_coverage_score >= 0.6 and channels_ok and critical_ok
    onboarding.onboarding_status = "ready" if ready else "failed"
    if ready and onboarding.ready_at is None:
        onboarding.ready_at = utc_now_func()
    if not ready:
        onboarding.ready_at = None

    runtime.available_slots = max(0, int(runtime.max_parallel_tasks or 0) - int(runtime.active_tasks_count or 0))
    runtime.status = "active" if worker.is_active else "paused"
    runtime.current_priority = runtime.current_priority or "idle"
    runtime.system_health_summary = {
        **dict(runtime.system_health_summary or {}),
        "knowledge_coverage": onboarding.knowledge_coverage_score,
        "connectors": {item["connector"]: item["status"] for item in onboarding.connector_checks},
        "channels": {item["channel"]: item["status"] for item in onboarding.channels_verified},
        "onboarding_status": onboarding.onboarding_status,
    }
    runtime.last_heartbeat = utc_now_func()
    runtime.updated_at = utc_now_func()
    await db.flush()
    return worker


async def refresh_all_workers_on_startup(
    db: AsyncSession,
    *,
    refresh_worker_startup_state_func,
) -> int:
    workers = (
        (
            await db.execute(
                select(AgentWorker)
                .options(selectinload(AgentWorker.onboarding), selectinload(AgentWorker.runtime_state))
                .where(AgentWorker.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for worker in workers:
        await refresh_worker_startup_state_func(db, worker)
    await db.commit()
    return len(workers)
