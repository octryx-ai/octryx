"""The secure-development execution context of a coding pipeline start: approved plan, scoped units, blockers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkChangePlan,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemStateEvent,
)
from ....time_utils import utc_now
from ..jira_values import blank_to_none, object_value, string_list
from ..plans.redeclare import SUPERSEDED_UNIT_STATUS


async def _execution_context(db: AsyncSession, item: WorkItem, payload: dict[str, Any]) -> dict[str, Any]:
    plan = await _resolve_approved_change_plan(db, item, blank_to_none(payload.get("change_plan_id")))
    selected_units = await _selected_change_units(db, item, payload.get("change_unit_ids"))
    blockers: list[dict[str, Any]] = []
    if plan is None:
        blockers.append(
            {
                "code": "approved_change_plan_required",
                "message": "Approved Change Plan required before secure development execution can start.",
            }
        )
    elif stale_plan := _stale_plan_blocker(item, plan):
        blockers.append(stale_plan)
    if not selected_units:
        blockers.append(
            {
                "code": "change_unit_required",
                "message": "At least one scoped Change Unit is required before secure development execution can start.",
            }
        )
    blockers.extend(_unit_blockers(plan, selected_units))
    validation_commands = _validation_commands(plan, selected_units)
    if not validation_commands:
        blockers.append(
            {
                "code": "validation_commands_required",
                "message": "Validation commands from the approved Change Plan or repository profile are required.",
            }
        )
    changed_files = string_list(payload.get("changed_files")) or string_list(payload.get("planned_changed_files"))
    out_of_scope = _out_of_scope_files(changed_files, selected_units)
    if out_of_scope:
        blockers.append(
            {
                "code": "out_of_scope_files",
                "message": "Requested changed files are outside the approved Change Unit paths.",
                "files": out_of_scope,
            }
        )
    return {
        "mode": "secure_local_development",
        "runtime": "local",
        "future_runtime": "eks_change_capsule",
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_plan_id": plan.id if plan else None,
        "change_plan_version": int(plan.version or 0) if plan else None,
        "change_unit_ids": [unit.id for unit in selected_units],
        "repositories": [_unit_execution_scope(unit) for unit in selected_units],
        "validation_commands": validation_commands,
        "changed_files": changed_files,
        "workspace_safety": {
            "isolated_branch_required": True,
            "approved_paths_only": True,
            "secret_access": "reference_only",
            "deployments": "disabled",
        },
        "blockers": blockers,
    }


def _unit_blockers(plan: WorkChangePlan | None, selected_units: list[WorkItemChangeUnit]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    plan_unit_ids = (
        {str(unit.get("id")) for unit in list(plan.change_units_json or []) if isinstance(unit, dict)}
        if plan
        else set()
    )
    for unit in selected_units:
        if plan_unit_ids and unit.id not in plan_unit_ids:
            blockers.append(
                {
                    "code": "change_unit_not_in_approved_plan",
                    "message": f"Change Unit {unit.id} is not part of the approved Change Plan.",
                    "change_unit_id": unit.id,
                }
            )
        if unit.missing_profile_fields_json:
            blockers.append(
                {
                    "code": "repository_profile_incomplete",
                    "message": f"Repository profile for {unit.repository_name} is incomplete.",
                    "change_unit_id": unit.id,
                    "missing_profile_fields": list(unit.missing_profile_fields_json or []),
                }
            )
        if not unit.expected_paths_json:
            blockers.append(
                {
                    "code": "approved_paths_required",
                    "message": f"Change Unit {unit.id} has no approved expected paths.",
                    "change_unit_id": unit.id,
                }
            )
    return blockers


def _stale_plan_blocker(item: WorkItem, plan: WorkChangePlan) -> dict[str, Any] | None:
    source_fields = object_value(item.source_fields_json)
    if source_fields.get("requires_replan"):
        return {
            "code": "source_requires_replan",
            "message": "Linked source evidence changed and requires a new approved Work Plan before execution.",
            "source_evidence": {
                "external_replan_reason": source_fields.get("external_replan_reason"),
                "latest_source_stale_event": source_fields.get("latest_source_stale_event"),
            },
        }
    if source_fields.get("source_evidence_stale"):
        return {
            "code": "source_evidence_stale",
            "message": (
                "Linked source evidence changed after planning; regenerate and approve the Work Plan "
                "before execution."
            ),
            "source_evidence": {"latest_source_stale_event": source_fields.get("latest_source_stale_event")},
        }
    source_updated = item.last_source_updated_at
    plan_cutoff = plan.approved_at or plan.decided_at or plan.updated_at or plan.created_at
    if source_updated and plan_cutoff and source_updated > plan_cutoff:
        return {
            "code": "source_changed_after_plan",
            "message": "Jira source evidence changed after the approved Work Plan; execution requires re-planning.",
            "source_evidence": {
                "last_source_updated_at": source_updated.isoformat(),
                "plan_cutoff_at": plan_cutoff.isoformat(),
            },
        }
    return None


def _apply_pipeline_work_item_state(
    db: AsyncSession,
    item: WorkItem,
    *,
    execution_context: dict[str, Any],
    current_user: User,
) -> None:
    previous = str(item.work_state or "").strip() or "intake"
    if previous in {"done", "closed", "cancelled"}:
        return
    blocker_codes = {str(blocker.get("code") or "") for blocker in execution_context.get("blockers", [])}
    if blocker_codes & {"source_requires_replan", "source_evidence_stale", "source_changed_after_plan"}:
        target = "needs_replan"
    elif blocker_codes:
        target = "needs_human_review"
    else:
        target = "in_progress"
    if previous == target:
        return
    item.work_state = target
    item.updated_at = utc_now()
    event = WorkItemStateEvent(
        work_item_id=item.id,
        from_state=previous,
        to_state=target,
        actor_id=current_user.id,
        reason="Coding pipeline start evaluated the approved plan, source freshness, and execution blockers.",
        source="coding_pipeline",
        dry_run=False,
        jira_sync_preview_json={"mode": "local_only", "will_mutate_jira": False},
        conflict_json={
            "change_plan_id": execution_context.get("change_plan_id"),
            "blockers": execution_context.get("blockers", []),
        },
    )
    db.add(event)


async def _resolve_approved_change_plan(
    db: AsyncSession,
    item: WorkItem,
    change_plan_id: str | None,
) -> WorkChangePlan | None:
    if change_plan_id:
        plan = await db.get(WorkChangePlan, change_plan_id)
        if plan is None or plan.work_item_id != item.id:
            return None
        return plan if plan.status == "approved" else None
    return (
        await db.execute(
            select(WorkChangePlan)
            .where(WorkChangePlan.work_item_id == item.id, WorkChangePlan.status == "approved")
            .order_by(WorkChangePlan.version.desc(), WorkChangePlan.approved_at.desc())
        )
    ).scalars().first()


async def _selected_change_units(
    db: AsyncSession,
    item: WorkItem,
    raw_ids: Any,
) -> list[WorkItemChangeUnit]:
    ids = string_list(raw_ids)
    stmt = (
        select(WorkItemChangeUnit)
        .where(
            WorkItemChangeUnit.work_item_id == item.id,
            WorkItemChangeUnit.status != SUPERSEDED_UNIT_STATUS,
        )
        .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
    )
    if ids:
        stmt = stmt.where(WorkItemChangeUnit.id.in_(ids))
    return list((await db.execute(stmt)).scalars().all())


def _validation_commands(plan: WorkChangePlan | None, units: list[WorkItemChangeUnit]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in list(plan.validation_plan_json or []) if plan else []:
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command") or "").strip()
        if command and command != "Manual verification required" and command not in seen:
            seen.add(command)
            commands.append(dict(entry))
    for unit in units:
        for command in unit.validation_commands_json or []:
            text = str(command).strip()
            if text and text not in seen:
                seen.add(text)
                commands.append({"command": text, "repository_name": unit.repository_name, "source": "change_unit"})
    return commands


def _out_of_scope_files(files: list[str], units: list[WorkItemChangeUnit]) -> list[str]:
    if not files:
        return []
    allowed = [
        str(path).strip()
        for unit in units
        for path in list(unit.expected_paths_json or [])
        if str(path).strip()
    ]
    if not allowed:
        return files
    return [path for path in files if not any(_path_allowed(path, approved) for approved in allowed)]


def _path_allowed(path: str, approved: str) -> bool:
    clean_path = path.strip().strip("/")
    clean_approved = approved.strip().strip("/")
    return clean_path == clean_approved or clean_path.startswith(f"{clean_approved}/")


def _unit_execution_scope(unit: WorkItemChangeUnit) -> dict[str, Any]:
    return {
        "change_unit_id": unit.id,
        "repository_name": unit.repository_name,
        "repository_profile_id": unit.repository_profile_id,
        "branch_name": unit.branch_name,
        "workspace_ref": f"local://secure-work/{unit.work_item_id}/{unit.id}",
        "expected_paths": list(unit.expected_paths_json or []),
        "validation_commands": list(unit.validation_commands_json or []),
        "status": unit.status,
    }
