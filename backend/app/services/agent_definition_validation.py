"""Fail-closed validation of an Agent Definition revision snapshot. No reference is taken as authority from the
snapshot: each is resolved again."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentGroup, ControlPlaneRuntimeTarget, Project
from .agent_definition_snapshot import (
    SNAPSHOT_DEFINITION_KEY,
    SNAPSHOT_STEPS_KEY,
)
from .agent_definition_validation_issues import ValidationIssue, ValidationResult, _result
from .agent_definition_validation_steps import _validate_step_order, _validate_steps
from .agent_reply_contract_schema import REPLY_CONTRACT_FIELD, ReplyContractError, normalize_reply_contract
from .agent_tool_surface_contract import (
    TOOL_SURFACE_FIELD,
    TOOL_SURFACE_NONE,
    normalize_tool_surface,
    step_needs_tools,
)
from .session.turn_preparation import VALID_THINKING_LEVELS

MAX_NAME_LENGTH = 200


async def publishable_agent_type_keys(db: AsyncSession) -> frozenset[str]:
    from .agent_mode import known_agent_mode_keys

    del db
    return known_agent_mode_keys()


async def _reference_exists(db: AsyncSession, model: Any, row_id: str) -> bool:
    return (
        await db.execute(select(model.id).where(model.id == row_id).limit(1))
    ).scalar_one_or_none() is not None


async def validate_definition_snapshot(
    db: AsyncSession, snapshot: dict[str, Any]
) -> ValidationResult:
    if not isinstance(snapshot, dict):
        return _result([ValidationIssue("malformed_snapshot", "snapshot")])

    definition = snapshot.get(SNAPSHOT_DEFINITION_KEY)
    steps = snapshot.get(SNAPSHOT_STEPS_KEY)
    issues: list[ValidationIssue] = []
    if not isinstance(definition, dict):
        issues.append(ValidationIssue("malformed_snapshot", SNAPSHOT_DEFINITION_KEY))
    if not isinstance(steps, list):
        issues.append(ValidationIssue("malformed_snapshot", SNAPSHOT_STEPS_KEY))
    if issues:
        return _result(issues)

    issues.extend(await _validate_header(db, definition))
    issues.extend(_validate_step_order(steps))
    issues.extend(_validate_steps(steps))
    issues.extend(_validate_tool_surface(definition, steps))
    issues.extend(_validate_reply_contract(definition))
    return _result(issues)


def _validate_reply_contract(definition: dict[str, Any]) -> list[ValidationIssue]:
    # A present value must be a valid contract, never read as text.
    if REPLY_CONTRACT_FIELD not in definition:
        return []
    try:
        normalize_reply_contract(definition[REPLY_CONTRACT_FIELD])
    except ReplyContractError:
        return [ValidationIssue("invalid_reply_contract", REPLY_CONTRACT_FIELD)]
    return []


def _validate_tool_surface(definition: dict[str, Any], steps: list[Any]) -> list[ValidationIssue]:
    # An unknown value, or no tools with tool-using steps, is refused.
    if TOOL_SURFACE_FIELD not in definition:
        return []
    try:
        # A present null, empty or unknown value is refused, never read as governed.
        surface = normalize_tool_surface(definition[TOOL_SURFACE_FIELD])
    except ValueError:
        return [ValidationIssue("unknown_tool_surface", TOOL_SURFACE_FIELD)]
    return [
        ValidationIssue("tool_surface_conflict", f"steps[{index}]", str(step.get("position") or ""))
        for index, step in enumerate(steps)
        if isinstance(step, dict) and surface == TOOL_SURFACE_NONE and step_needs_tools(step)
    ]


async def _validate_header(
    db: AsyncSession, definition: dict[str, Any]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    name = str(definition.get("name") or "").strip()
    if not name:
        issues.append(ValidationIssue("missing_name", "name"))
    elif len(name) > MAX_NAME_LENGTH:
        issues.append(ValidationIssue("name_too_long", "name"))

    agent_type = str(definition.get("agent_type") or "").strip()
    if agent_type not in await publishable_agent_type_keys(db):
        issues.append(ValidationIssue("unknown_agent_type", "agent_type", agent_type))

    thinking_level = str(definition.get("thinking_level") or "").strip()
    if thinking_level not in VALID_THINKING_LEVELS:
        issues.append(
            ValidationIssue("unknown_thinking_level", "thinking_level", thinking_level)
        )

    if not isinstance(definition.get("skill_preferences"), dict):
        issues.append(ValidationIssue("malformed_skill_preferences", "skill_preferences"))

    for field, model, code in (
        ("project_id", Project, "unknown_project"),
        ("runtime_target_id", ControlPlaneRuntimeTarget, "unknown_runtime_target"),
    ):
        reference = definition.get(field)
        if reference is None:
            continue
        reference_id = str(reference).strip()
        if not reference_id:
            # An empty string is ambiguous between "unset" and "broken"; the
            # snapshot builder writes NULL for unset, so this is malformed.
            issues.append(ValidationIssue("malformed_reference", field))
            continue
        if not await _reference_exists(db, model, reference_id):
            issues.append(ValidationIssue(code, field, reference_id))

    issues.extend(
        await _validate_group_scope(
            db,
            group_reference=definition.get("group_id"),
            definition_project_id=str(definition.get("project_id") or "").strip() or None,
        )
    )
    return issues


async def _validate_group_scope(
    db: AsyncSession,
    *,
    group_reference: Any,
    definition_project_id: str | None,
) -> list[ValidationIssue]:
    # The group's Workspace must match exactly: an unassigned group on a Workspace definition is a cross-scope binding.
    if group_reference is None:
        return []
    group_id = str(group_reference).strip()
    if not group_id:
        return [ValidationIssue("malformed_reference", "group_id")]
    row = (
        await db.execute(
            select(AgentGroup.project_id).where(AgentGroup.id == group_id).limit(1)
        )
    ).first()
    if row is None:
        return [ValidationIssue("unknown_group", "group_id", group_id)]
    group_project_id = str(row[0] or "").strip() or None
    if group_project_id != definition_project_id:
        return [ValidationIssue("group_project_mismatch", "group_id", group_id)]
    return []


__all__ = [
    "publishable_agent_type_keys",
    "validate_definition_snapshot",
]
