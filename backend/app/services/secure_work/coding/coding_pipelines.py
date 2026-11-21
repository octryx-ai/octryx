from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    AuditLog,
    User,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkItem,
)
from ....time_utils import utc_now
from ...access_control import require_existing_workspace
from ..coding_serializers import serialize_coding_pipeline_config, serialize_coding_pipeline_run
from ..config_visibility import scope_filter, unmasked, visible_rows
from ..jira_values import blank_to_none, object_value, string_list
from .pipeline_checks import normalize_checks
from .pipeline_config_choice import item_pipeline_configs, resolve_item_pipeline_config
from .pipeline_execution_context import _apply_pipeline_work_item_state, _execution_context
from .pipeline_stages import (
    _initial_stage_results,
    _new_pipeline_run,
    _normalize_stages,
    _object_items,
    _refresh_run_status,
    _run_stages,
    _stage_definitions,
    _stage_from_definition,
)

TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "policy_blocked"}
CONTROL_ACTIONS = {"pause", "resume", "cancel"}


async def list_coding_pipeline_configs(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    include_inactive: bool = False,
    project_scope: set[str] | None = None,
) -> list[dict[str, Any]]:
    stmt = select(WorkCodingPipelineConfig)
    if project_scope is not None:  # r10 C-8f: the caller's Workspaces and the global rows (read-only)
        stmt = stmt.where(scope_filter(WorkCodingPipelineConfig, project_scope))
    if project_id:
        stmt = stmt.where(WorkCodingPipelineConfig.project_id == project_id)
    if not include_inactive:
        stmt = stmt.where(WorkCodingPipelineConfig.is_active.is_(True))
    stmt = stmt.order_by(WorkCodingPipelineConfig.name.asc())
    return visible_rows(map(serialize_coding_pipeline_config, (await db.execute(stmt)).scalars()), project_scope)


async def create_coding_pipeline_config(
    db: AsyncSession,
    *,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = await _normalized_config_payload(db, payload)
    row = WorkCodingPipelineConfig(**normalized, created_by=current_user.id, updated_by=current_user.id)
    db.add(row)
    await db.flush()
    return serialize_coding_pipeline_config(row)


async def update_coding_pipeline_config(
    db: AsyncSession,
    *,
    config_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = await _get_config(db, config_id)
    payload = {"project_id": row.project_id, **unmasked(payload, serialize_coding_pipeline_config(row))}  # C-8c, R11-4
    normalized = await _normalized_config_payload(db, payload)
    for key, value in normalized.items():
        setattr(row, key, value)
    row.updated_by = current_user.id
    await db.flush()
    return serialize_coding_pipeline_config(row)


async def get_coding_pipeline_trace(db: AsyncSession, work_item_id: str) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    run = (
        await db.execute(
            select(WorkCodingPipelineRun)
            .where(WorkCodingPipelineRun.work_item_id == item.id)
            .order_by(WorkCodingPipelineRun.started_at.desc())
        )
    ).scalars().first()
    if run is None:
        return {
            "work_item_id": item.id,
            "run": None,
            "stages": [],
            "available_configs": await item_pipeline_configs(db, item),
        }
    stages = await _run_stages(db, run.id)
    return {
        "work_item_id": item.id,
        "run": serialize_coding_pipeline_run(run, stages),
        "stages": [stage for stage in serialize_coding_pipeline_run(run, stages)["stages"]],
        "available_configs": await item_pipeline_configs(db, item),
    }


async def start_coding_pipeline_run(
    db: AsyncSession,
    *,
    work_item_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    item = await _get_work_item(db, work_item_id)
    config = await resolve_item_pipeline_config(db, current_user, blank_to_none(payload.get("config_id")), item)
    stages = _stage_definitions(config)
    if not stages:
        raise HTTPException(status_code=422, detail="Pipeline config must define at least one stage")
    execution_context = await _execution_context(db, item, payload)
    _apply_pipeline_work_item_state(db, item, execution_context=execution_context, current_user=current_user)
    stage_results = _initial_stage_results(stages, payload.get("stage_results"), execution_context)
    run = _new_pipeline_run(item, config, stages, execution_context, current_user)
    db.add(run)
    await db.flush()
    for index, definition in enumerate(stages):
        result = stage_results.get(definition["key"], {})
        db.add(_stage_from_definition(run, definition, index, result, current_user.id))
    await db.flush()
    await _refresh_run_status(db, run, current_user.id)
    action = (
        "secure_work.coding_pipeline_policy_blocked"
        if execution_context["blockers"]
        else "secure_work.coding_pipeline_started"
    )
    db.add(
        _audit_log(
            current_user,
            item,
            action,
            {
                "run_id": run.id,
                "change_plan_id": execution_context.get("change_plan_id"),
                "change_unit_ids": execution_context.get("change_unit_ids", []),
                "blockers": execution_context["blockers"],
            },
        )
    )
    await db.flush()
    return serialize_coding_pipeline_run(run, await _run_stages(db, run.id))


async def update_coding_pipeline_stage(
    db: AsyncSession,
    *,
    run_id: str,
    stage_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    run = await _get_run(db, run_id)
    stage = await db.get(WorkCodingPipelineStage, stage_id)
    if stage is None or stage.run_id != run.id:
        raise HTTPException(status_code=404, detail="Pipeline stage not found")
    status = str(payload.get("status") or stage.status).strip()
    if status not in {"pending", "ready", "running", "completed", "failed", "policy_blocked", "skipped"}:
        raise HTTPException(status_code=422, detail="Unsupported stage status")
    now = utc_now()
    stage.status = status
    stage.inputs_json = object_value(payload.get("inputs")) or stage.inputs_json
    stage.outputs_json = object_value(payload.get("outputs")) or stage.outputs_json
    stage.evidence_json = _object_items(payload.get("evidence")) or stage.evidence_json
    stage.required_actions_json = string_list(payload.get("required_actions")) or stage.required_actions_json
    stage.policy_refs_json = _object_items(payload.get("policy_refs")) or stage.policy_refs_json
    stage.updated_by = current_user.id
    if status == "running" and not stage.started_at:
        stage.started_at = now
    if status in {"completed", "failed", "policy_blocked", "skipped"}:
        stage.completed_at = now
    await db.flush()
    await _refresh_run_status(db, run, current_user.id)
    item = await _get_work_item(db, run.work_item_id)
    db.add(
        _audit_log(
            current_user,
            item,
            "secure_work.coding_pipeline_stage_updated",
            {"run_id": run.id, "stage_id": stage.id, "stage_key": stage.stage_key, "status": status},
        )
    )
    await db.flush()
    return serialize_coding_pipeline_run(run, await _run_stages(db, run.id))


async def control_coding_pipeline_run(
    db: AsyncSession,
    *,
    run_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    run = await _get_run(db, run_id)
    action = str(payload.get("action") or "").strip().lower()
    if action not in CONTROL_ACTIONS:
        raise HTTPException(status_code=422, detail="action must be pause, resume, or cancel")
    if run.status in TERMINAL_RUN_STATUSES and action != "resume":
        raise HTTPException(status_code=409, detail=f"Pipeline run is already {run.status}")
    now = utc_now()
    if action == "pause":
        run.control_state = "paused"
        run.status = "paused"
    elif action == "resume":
        run.control_state = "running"
        run.status = "running"
    else:
        run.control_state = "cancelled"
        run.status = "cancelled"
        run.completed_at = now
    run.updated_by = current_user.id
    run.updated_at = now
    run.recovery_state_json = {**dict(run.recovery_state_json or {}), "last_control_action": action}
    item = await _get_work_item(db, run.work_item_id)
    db.add(_audit_log(current_user, item, f"secure_work.coding_pipeline_{action}", {"run_id": run.id}))
    await db.flush()
    return serialize_coding_pipeline_run(run, await _run_stages(db, run.id))


async def _normalized_config_payload(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = blank_to_none(payload.get("project_id"))
    await require_existing_workspace(db, project_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    stages = _normalize_stages(payload.get("stages"))
    return {
        "name": name[:220],
        "description": blank_to_none(payload.get("description")),
        "project_id": project_id,
        "scope_json": object_value(payload.get("scope")),
        "stages_json": stages,
        "required_stage_keys_json": string_list(payload.get("required_stage_keys")) or [
            stage["key"] for stage in stages if stage.get("required")
        ],
        # the checks on every change live with the pipeline's controls.
        "controls_json": {
            **(object_value(payload.get("controls")) or {"pause": True, "resume": True, "cancel": True}),
            "checks": normalize_checks(payload.get("checks", object_value(payload.get("controls")).get("checks"))),
        },
        "review_status": str(payload.get("review_status") or "needs_review").strip()[:80],
        "is_active": bool(payload.get("is_active", True)),
    }


async def _get_config(db: AsyncSession, config_id: str) -> WorkCodingPipelineConfig:
    row = await db.get(WorkCodingPipelineConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Coding pipeline config not found")
    return row


async def _get_work_item(db: AsyncSession, work_item_id: str) -> WorkItem:
    row = await db.get(WorkItem, work_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    return row


async def _get_run(db: AsyncSession, run_id: str) -> WorkCodingPipelineRun:
    row = await db.get(WorkCodingPipelineRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Coding pipeline run not found")
    return row


def _audit_log(current_user: User, item: WorkItem, action: str, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        user_id=current_user.id,
        action=action,
        resource_type="secure_work_coding_pipeline",
        resource_id=item.id,
        details={"work_item_id": item.id, "source_key": item.source_key, **details},
    )
