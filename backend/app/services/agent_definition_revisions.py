"""Agent Definition revision lifecycle."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinition, AgentDefinitionRevision, AgentStep, User
from ..models.agent.agent_definition_revision import (
    REVISION_STATUS_DRAFT,
    REVISION_STATUS_PUBLISHED,
)
from ..time_utils import utc_now
from .agent_definition_access import authorize_restore_target_scope
from .agent_definition_revision_store import NOT_PUBLISHED_DETAIL, insert_revision, load_definition_steps
from .agent_definition_snapshot import (
    build_definition_snapshot,
    compute_snapshot_checksum,
    snapshot_header,
    snapshot_steps,
)
from .agent_definition_validation import validate_definition_snapshot
from .agent_reply_contract import declared_reply_contract, reply_contract_column
from .agent_tool_surface_contract import declared_tool_surface


async def next_revision_number(db: AsyncSession, definition_id: str) -> int:
    current_max = (
        await db.execute(
            select(func.max(AgentDefinitionRevision.revision_number)).where(
                AgentDefinitionRevision.definition_id == definition_id
            )
        )
    ).scalar_one()
    return int(current_max or 0) + 1


async def create_draft_revision(
    db: AsyncSession, *, definition: AgentDefinition, created_by: str
) -> AgentDefinitionRevision:
    # Not validated: drafting must succeed so a broken definition can be captured and its reasons read.
    steps = await load_definition_steps(db, definition.id)
    snapshot = build_definition_snapshot(definition, steps)
    revision = AgentDefinitionRevision(
        id=str(uuid.uuid4()),
        definition_id=definition.id,
        revision_number=await next_revision_number(db, definition.id),
        status=REVISION_STATUS_DRAFT,
        checksum=compute_snapshot_checksum(snapshot),
        created_by=created_by,
        created_at=utc_now(),
    )
    revision.snapshot = snapshot
    await insert_revision(db, revision)
    return revision


async def restore_revision(
    db: AsyncSession,
    *,
    revision: AgentDefinitionRevision,
    definition: AgentDefinition,
    current_user: User,
) -> AgentDefinitionRevision:
    # The target Workspace is re-authorized before any field is applied; nothing is written when authorization or
    # validation fails.
    if revision.status != REVISION_STATUS_PUBLISHED:
        raise HTTPException(status_code=409, detail=NOT_PUBLISHED_DETAIL)
    await authorize_restore_target_scope(
        db, current_user=current_user, definition=definition, revision=revision
    )
    restored_by = current_user.id
    snapshot = revision.snapshot
    result = await validate_definition_snapshot(db, snapshot)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail={"message": "Revision can no longer be restored", **result.as_dict()},
        )

    _apply_header(definition, snapshot_header(snapshot))
    await _apply_steps(db, definition, snapshot_steps(snapshot))

    restored = AgentDefinitionRevision(
        id=str(uuid.uuid4()),
        definition_id=definition.id,
        revision_number=await next_revision_number(db, definition.id),
        status=REVISION_STATUS_PUBLISHED,
        checksum=compute_snapshot_checksum(snapshot),
        restored_from_revision_id=revision.id,
        created_by=restored_by,
        created_at=utc_now(),
        published_by=restored_by,
        published_at=utc_now(),
    )
    restored.snapshot = snapshot
    restored.validation = result.as_dict()
    await insert_revision(db, restored)
    return restored


def _apply_header(definition: AgentDefinition, header: dict[str, Any]) -> None:
    # ``owner_id`` is not in the snapshot, so a restore can never move ownership.
    definition.name = str(header.get("name") or "")
    definition.description = str(header.get("description") or "")
    definition.goal = str(header.get("goal") or "")
    definition.agent_type = str(header.get("agent_type") or "")
    definition.thinking_level = str(header.get("thinking_level") or "")
    definition.branch_prefix = str(header.get("branch_prefix") or "")
    definition.system_prompt = str(header.get("system_prompt") or "")
    definition.output_prompt = str(header.get("output_prompt") or "")
    definition.project_id = header.get("project_id") or None
    definition.group_id = header.get("group_id") or None
    definition.runtime_target_id = header.get("runtime_target_id") or None
    definition.require_self_review = bool(header.get("require_self_review"))
    # Validated before this point; an invalid present value would raise here rather than widen.
    definition.tool_surface = declared_tool_surface(header)
    # A missing key restores text; a present value was validated and is stored canonically.
    reply_contract = declared_reply_contract(header)
    definition.reply_contract_json = None if reply_contract is None else reply_contract_column(reply_contract)
    definition.is_active = bool(header.get("is_active"))
    definition.skill_preferences = header.get("skill_preferences") or {}


async def _apply_steps(
    db: AsyncSession, definition: AgentDefinition, steps: list[dict[str, Any]]
) -> None:
    # The live row may carry duplicate positions: the first is the update target, every further one is surplus.
    existing: dict[int, AgentStep] = {}
    surplus: list[AgentStep] = []
    for step in await load_definition_steps(db, definition.id):
        position = int(step.position or 0)
        if position in existing:
            surplus.append(step)
        else:
            existing[position] = step

    snapshot_positions = {int(step.get("position") or 0) for step in steps}
    surplus.extend(
        step for position, step in existing.items() if position not in snapshot_positions
    )
    for step in surplus:
        await db.delete(step)

    for payload in steps:
        position = int(payload.get("position") or 0)
        # ``existing`` holds only the first step per position, so this never
        # resolves to a surplus duplicate that was just deleted.
        step = existing.get(position)
        if step is None:
            step = AgentStep(
                id=str(uuid.uuid4()), agent_id=definition.id, position=position
            )
            db.add(step)
        _apply_step_fields(step, payload)
    await db.flush()


def _apply_step_fields(step: AgentStep, payload: dict[str, Any]) -> None:
    step.position = int(payload.get("position") or 0)
    step.name = str(payload.get("name") or "")
    step.step_type = str(payload.get("step_type") or "")
    step.instructions = str(payload.get("instructions") or "")
    step.success_criteria = str(payload.get("success_criteria") or "")
    step.allowed_tools = list(payload.get("allowed_tools") or [])
    step.step_config = payload.get("step_config") or {}
    step.is_enabled = bool(payload.get("is_enabled"))


__all__ = [
    "create_draft_revision",
    "next_revision_number",
    "restore_revision",
]
