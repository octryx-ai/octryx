"""Coding pipeline stages: definitions, stage rows, preflight results and the run status derived from them."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkCodingPipelineStage,
    WorkItem,
)
from ....time_utils import utc_now
from ..jira_values import list_value, object_value, string_list
from .coding_state_machine import evaluate_coding_state_machine

DEFAULT_PIPELINE_STAGES: list[dict[str, Any]] = [
    {"key": "intake", "label": "Intake and repository resolution", "required": True},
    {"key": "context_collection", "label": "Context collection", "required": True},
    {"key": "change_plan", "label": "Change plan generation", "required": True},
    {"key": "policy_preflight", "label": "Policy preflight", "required": True},
    {"key": "branch_worktree", "label": "Branch/worktree creation", "required": True},
    {"key": "implementation", "label": "Implementation iterations", "required": True},
    {"key": "local_validation", "label": "Local validation", "required": True},
    {"key": "diff_review", "label": "Diff review and policy post-check", "required": True},
    {"key": "ci_cd", "label": "CI/CD execution", "required": False},
    {"key": "human_feedback", "label": "Human review feedback handling", "required": True},
    {"key": "pr_update", "label": "PR creation/update", "required": True},
    {"key": "acceptance_closeout", "label": "Acceptance state and closeout", "required": True},
]


async def _run_stages(db: AsyncSession, run_id: str) -> list[WorkCodingPipelineStage]:
    return (
        await db.execute(
            select(WorkCodingPipelineStage)
            .where(WorkCodingPipelineStage.run_id == run_id)
            .order_by(WorkCodingPipelineStage.stage_order.asc())
        )
    ).scalars().all()


async def _refresh_run_status(db: AsyncSession, run: WorkCodingPipelineRun, actor_id: str) -> None:
    stages = await _run_stages(db, run.id)
    statuses = [stage.status for stage in stages]
    now = utc_now()
    if "policy_blocked" in statuses:
        run.status = "policy_blocked"
        run.control_state = "blocked"
        run.completed_at = now
    elif "failed" in statuses:
        run.status = "failed"
        run.control_state = "blocked"
        run.completed_at = now
    elif stages and all(status in {"completed", "skipped"} for status in statuses):
        run.status = "completed"
        run.control_state = "completed"
        run.completed_at = now
    else:
        run.status = "running"
        run.control_state = "running"
        run.completed_at = None
    active = next((stage for stage in stages if stage.status in {"policy_blocked", "failed"}), None)
    if active is None:
        active = next((stage for stage in stages if stage.status in {"running", "ready", "pending"}), None)
    run.current_stage_key = active.stage_key if active else None
    state_machine = evaluate_coding_state_machine(stages, summary=run.summary_json, run_status=run.status)
    if state_machine["status"] == "blocked" and run.status == "completed":
        run.status = "blocked"
        run.control_state = "blocked"
        run.completed_at = None
        run.current_stage_key = state_machine["phase"]
    run.updated_by = actor_id
    run.updated_at = now
    run.summary_json = _run_summary(stages, run.summary_json, state_machine=state_machine)


def _stage_definitions(config: WorkCodingPipelineConfig | None) -> list[dict[str, Any]]:
    return _normalize_stages(config.stages_json if config else DEFAULT_PIPELINE_STAGES)


def _normalize_stages(value: Any) -> list[dict[str, Any]]:
    raw = list_value(value) or DEFAULT_PIPELINE_STAGES
    stages: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        label = str(entry.get("label") or key).strip()
        if key and label:
            stages.append({"key": key[:120], "label": label[:220], "required": bool(entry.get("required", True))})
    return stages or DEFAULT_PIPELINE_STAGES


def _stage_result_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {str(key): object_value(result) for key, result in value.items()}


def _stage_from_definition(
    run: WorkCodingPipelineRun,
    definition: dict[str, Any],
    index: int,
    result: dict[str, Any],
    actor_id: str,
) -> WorkCodingPipelineStage:
    status = str(result.get("status") or ("ready" if index == 0 else "pending")).strip()
    now = utc_now()
    completed = status in {"completed", "failed", "policy_blocked", "skipped"}
    return WorkCodingPipelineStage(
        run_id=run.id,
        stage_key=definition["key"],
        label=definition["label"],
        stage_order=index,
        status=status,
        required=bool(definition.get("required", True)),
        inputs_json=object_value(result.get("inputs")),
        outputs_json=object_value(result.get("outputs")),
        evidence_json=_object_items(result.get("evidence")),
        required_actions_json=string_list(result.get("required_actions")),
        policy_refs_json=_object_items(result.get("policy_refs")),
        started_at=now if status == "running" else None,
        completed_at=now if completed else None,
        updated_by=actor_id,
    )


def _blocked_stage_results(
    stages: list[dict[str, Any]],
    execution_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    target_key = "policy_preflight" if any(stage["key"] == "policy_preflight" for stage in stages) else stages[0]["key"]
    return {
        target_key: {
            "status": "policy_blocked",
            "inputs": {"execution_context": execution_context},
            "evidence": [{"kind": "secure_development_scope_check", "status": "blocked"}],
            "policy_refs": execution_context["blockers"],
            "required_actions": [blocker["message"] for blocker in execution_context["blockers"]],
        }
    }


def _merge_preflight_stage_results(
    stages: list[dict[str, Any]],
    stage_results: dict[str, dict[str, Any]],
    execution_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    target_key = "policy_preflight" if any(stage["key"] == "policy_preflight" for stage in stages) else stages[0]["key"]
    current = dict(stage_results.get(target_key) or {})
    evidence = _object_items(current.get("evidence"))
    evidence.append({"kind": "secure_development_scope_check", "status": "passed"})
    current["inputs"] = {**dict(current.get("inputs") or {}), "execution_context": execution_context}
    current["evidence"] = evidence
    stage_results[target_key] = current
    return stage_results


def _run_summary(
    stages: list[WorkCodingPipelineStage],
    existing: dict[str, Any] | None = None,
    *,
    state_machine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    required_actions: list[str] = []
    for stage in stages:
        counts[stage.status] = counts.get(stage.status, 0) + 1
        required_actions.extend(str(action) for action in stage.required_actions_json or [])
    preserved = {
        key: value
        for key, value in dict(existing or {}).items()
        if key not in {"stage_count", "counts", "required_actions"}
    }
    summary = {**preserved, "stage_count": len(stages), "counts": counts, "required_actions": required_actions[:20]}
    if state_machine is not None:
        summary["state_machine"] = state_machine
    return summary


def _object_items(value: Any) -> list[dict[str, Any]]:
    return [dict(entry) for entry in list_value(value) if isinstance(entry, dict)]


def _initial_stage_results(
    stages: list[dict[str, Any]], raw_results: Any, execution_context: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    stage_results = _stage_result_map(raw_results)
    if execution_context["blockers"]:
        return _blocked_stage_results(stages, execution_context)
    return _merge_preflight_stage_results(stages, stage_results, execution_context)


def _new_pipeline_run(
    item: WorkItem,
    config: WorkCodingPipelineConfig | None,
    stages: list[dict[str, Any]],
    execution_context: dict[str, Any],
    current_user: User,
) -> WorkCodingPipelineRun:
    now = utc_now()
    return WorkCodingPipelineRun(
        work_item_id=item.id,
        config_id=config.id if config else None,
        status="policy_blocked" if execution_context["blockers"] else "running",
        control_state="blocked" if execution_context["blockers"] else "running",
        current_stage_key=stages[0]["key"],
        summary_json={
            "source": "secure_development_start",
            "stage_count": len(stages),
            "execution_context": execution_context,
        },
        recovery_state_json={
            "resume_from_stage": stages[0]["key"],
            "change_plan_id": execution_context.get("change_plan_id"),
            "change_unit_ids": execution_context.get("change_unit_ids", []),
        },
        started_by=current_user.id,
        updated_by=current_user.id,
        started_at=now,
        updated_at=now,
    )
