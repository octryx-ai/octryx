"""Agent Definition revision lifecycle.

Owns draft creation, validation persistence, publication, and restore for
:class:`~app.models.agent.agent_definition_revision.AgentDefinitionRevision`.
Callers resolve and authorize the definition through
:mod:`app.services.agent_definition_access` before reaching any function here.

One authorization rule is enforced *inside* this module rather than by the
caller: ``restore_revision`` re-authorizes the Workspace its snapshot would write
onto the live row. That check depends on snapshot content only this writer reads,
so leaving it to the transport would make an alternate caller — a worker, a
future bulk endpoint, a test helper — silently able to move a definition into a
Workspace nobody authorized. It therefore takes the authenticated ``User``, not
an attribution string.

Transaction boundary: every function only ``flush()``es. ``app.db.get_db``
commits once the request handler returns and rolls back on any exception, so
``restore_revision`` — which rewrites the live aggregate *and* appends a
revision — is atomic without a nested transaction.

Publication is fail-closed and re-validated at publish time rather than trusting
a stored verdict, so a revision cannot be published on the strength of a
validation that has since gone stale (a deleted project, a removed runtime
target, a retired tool). A failed publish raises 422 and therefore persists
nothing; the ``invalid`` status is written by ``validate_revision``, which is the
endpoint whose job is to record a verdict.
"""

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
    """Snapshot the current live aggregate into a new immutable draft revision.

    The revision is not validated here: drafting must always succeed so an
    administrator can capture a broken definition and then read the reasons it
    cannot be published.
    """
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
    """Restore a published revision onto the live aggregate.

    *current_user* is the authenticated caller, not an attribution string: the
    Workspace this snapshot would write onto the live row is re-authorized here,
    before any field is applied, so no caller of this writer can move a
    definition into (or out of) a Workspace it has no authority in. 403 for an
    unauthorized target; the caller is already authorized to read the revision,
    so the target id is not new information to them.

    The snapshot is then re-validated, so a revision whose project, runtime
    target, or tools have since disappeared cannot be restored. Nothing is
    written when authorization or validation fails.

    Returns the new published revision, which carries the same content checksum
    as its source and records ``restored_from_revision_id`` lineage.
    """
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
    """Write snapshot header fields back onto the live definition.

    ``owner_id`` is deliberately absent from the snapshot, so a restore can
    never move ownership of a definition.
    """
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
    """Reconcile the live steps with the snapshot, keyed by position.

    Validation guarantees the snapshot's positions are exactly ``1..len(steps)``,
    so position is a stable key: steps present in both are updated in place,
    steps missing from the live row are recreated, and steps added after the
    snapshot was taken are deleted.

    The *live* row is not validated (panel CRUD never was), so it may carry
    duplicate positions. The first step at a position is the update target and
    every further one is surplus, which makes restore converge on exactly the
    snapshot's step set.
    """
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
