"""Checks on every change, declared on the Workspace's delivery pipeline."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkCodingPipelineConfig, WorkCodingPolicy, WorkItem
from ...access_control import require_visible_workspace
from ..access import get_scoped_work_item
from ..jira_values import blank_to_none, object_value
from ..plans.repository_planning import list_work_item_change_units
from ..related_rows import CHANGE_PLAN, load_optional_related
from .coding_policy_evaluator import collect_change_evidence, evaluate_policy, summarize_outcomes

CHECK_TYPES = {
    "pr_size_threshold": "PR size",
    "file_line_threshold": "File size",
    "test_requirement": "Test evidence",
    "documentation_requirement": "Docs touched",
    "branch_commit_naming": "Branch naming",
    "dependency_change": "Dependency change",
}
EFFECTS = {"warn": "warn", "review": "review_required", "block": "block"}
KEY = re.compile(r"[^a-z0-9_]+")


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"state": "invalid_request", "field": "checks", "message": message})


def normalize_checks(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise _refuse("checks must be a list")
    checks: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("type") not in CHECK_TYPES:
            raise _refuse(f"check type must be one of: {', '.join(CHECK_TYPES)}")
        effect = str(entry.get("effect") or "warn")
        if effect not in EFFECTS:
            raise _refuse("check effect must be warn, review or block")
        key = KEY.sub("_", str(entry.get("key") or entry["type"]).lower()).strip("_")[:80] or entry["type"]
        if any(check["key"] == key for check in checks):
            raise _refuse(f"check key {key} is used twice")
        label = str(entry.get("label") or CHECK_TYPES[entry["type"]]).strip()[:120]
        checks.append(
            {
                "key": key,
                "type": entry["type"],
                "label": label,
                "effect": effect,
                "rule": object_value(entry.get("rule")),
            }
        )
    return checks


def checks_of(config: WorkCodingPipelineConfig | None) -> list[dict[str, Any]]:
    checks = (dict(config.controls_json or {}) if config is not None else {}).get("checks")
    return [check for check in checks if isinstance(check, dict)] if isinstance(checks, list) else []


def as_rule(config: WorkCodingPipelineConfig, check: dict[str, Any]) -> WorkCodingPolicy:
    return WorkCodingPolicy(
        id=f"check:{config.id}:{check['key']}",
        name=check["label"],
        project_id=config.project_id,
        policy_type=check["type"],
        severity="medium",
        enforcement_mode=EFFECTS[check["effect"]],
        scope_json={},
        rule_json=dict(check.get("rule") or {}),
        exceptions_json=[],
    )


async def workspace_pipelines(db: AsyncSession, project_id: str | None) -> list[WorkCodingPipelineConfig]:
    stmt = select(WorkCodingPipelineConfig).where(WorkCodingPipelineConfig.is_active.is_(True))
    stmt = (
        stmt.where((WorkCodingPipelineConfig.project_id == project_id) | WorkCodingPipelineConfig.project_id.is_(None))
        if project_id
        else stmt.where(WorkCodingPipelineConfig.project_id.is_(None))
    )
    return list((await db.execute(stmt.order_by(WorkCodingPipelineConfig.name))).scalars())


async def preview_pipeline_checks(db: AsyncSession, *, payload: dict[str, Any], current_user: User) -> dict[str, Any]:
    explicit_project = blank_to_none(payload.get("project_id"))
    await require_visible_workspace(db, current_user.id, explicit_project)
    item_id, plan_id = blank_to_none(payload.get("work_item_id")), blank_to_none(payload.get("change_plan_id"))
    item = await get_scoped_work_item(db, current_user, item_id) if item_id else None
    plan = await load_optional_related(db, current_user, CHANGE_PLAN, plan_id)
    if plan is not None:
        if item is not None and plan.work_item_id != item.id:
            raise HTTPException(status_code=422, detail="change_plan_id belongs to another Work Item")
        item = item or await db.get(WorkItem, plan.work_item_id)
    if explicit_project is not None and item is not None and item.project_id != explicit_project:
        raise HTTPException(status_code=422, detail="project_id does not match the Work Item's Workspace")
    units = payload.get("change_units")
    if not isinstance(units, list):
        units = await list_work_item_change_units(db, item.id) if item else []
    evidence = collect_change_evidence(work_item=item, change_plan=plan, change_units=units, payload=payload)
    project_id = explicit_project or (item.project_id if item else None)
    outcomes = [
        evaluate_policy(as_rule(config, check), evidence)
        for config in await workspace_pipelines(db, project_id)
        for check in checks_of(config)
    ]
    return {
        "summary": summarize_outcomes(outcomes),
        "outcomes": outcomes,
        "evidence": {
            key: evidence[key]
            for key in (
                "repositories",
                "branches",
                "paths",
                "changed_file_count",
                "changed_lines",
                "validation_commands",
            )
        },
    }


__all__ = ["CHECK_TYPES", "EFFECTS", "checks_of", "normalize_checks", "preview_pipeline_checks", "workspace_pipelines"]
