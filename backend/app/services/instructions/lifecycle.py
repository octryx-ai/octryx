"""Lifecycle of an instruction: create, new draft version, submit, publish, retire, seed.

Every operation refuses with a closed :class:`InstructionRefusal` code. A version is append-only. Submit
runs the conflict check (``conflicts.check_conflicts``) and creates the four-eyes approval; findings block
it unless the submitter accepts them. Publish needs that approval approved through the platform's single
four-eyes decision (``services/governance/four_eyes``); the approver is a global admin, or an admin/owner
of the instruction's Workspace. Every change writes an audit row with ids, versions and digests only.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.instruction import (
    INSTRUCTION_BINDING_ALWAYS,
    INSTRUCTION_BINDING_WORKFLOW,
    INSTRUCTION_BINDINGS,
    INSTRUCTION_SCOPE_GLOBAL,
    INSTRUCTION_STATUS_ACTIVE,
    INSTRUCTION_STATUS_RETIRED,
    Instruction,
    InstructionVersion,
)
from ...time_utils import utc_now
from .contract import KEY_PATTERN
from .lifecycle_core import (
    InstructionRefusal,
    _add_version,
    _audit,
    _checked_body,
    _checked_scope,
    _facts,
    load_instruction,
)
from .seeds import SEEDS


async def create_instruction(
    db: AsyncSession, *, key: str, title: str, scope_type: str, scope_id: str | None, workflow_key: str | None,
    body: str, change_note: str, user: User, binding: str | None = None,
) -> tuple[Instruction, InstructionVersion]:
    normalized_key = str(key or "").strip()
    if not re.match(KEY_PATTERN, normalized_key):
        raise InstructionRefusal("instruction_key_invalid", 422)
    if not str(title or "").strip():
        raise InstructionRefusal("instruction_title_required", 422)
    kind, ident = await _checked_scope(db, scope_type, scope_id)
    bound_workflow = str(workflow_key or "").strip() or None
    mode = str(binding or (INSTRUCTION_BINDING_WORKFLOW if bound_workflow else INSTRUCTION_BINDING_ALWAYS))
    if mode not in INSTRUCTION_BINDINGS or (mode == INSTRUCTION_BINDING_WORKFLOW) != (bound_workflow is not None):
        raise InstructionRefusal("instruction_binding_invalid", 422)
    text = _checked_body(body)
    existing = (
        await db.execute(
            select(Instruction).where(
                Instruction.key == normalized_key, Instruction.scope_type == kind,
                Instruction.scope_id.is_(None) if ident is None else Instruction.scope_id == ident,
            )
        )
    ).scalars().first()
    if existing is not None:
        raise InstructionRefusal("instruction_key_exists", key=normalized_key)
    instruction = Instruction(
        key=normalized_key, title=str(title).strip()[:220], scope_type=kind, scope_id=ident, binding=mode,
        workflow_key=bound_workflow, status=INSTRUCTION_STATUS_ACTIVE, created_by=user.id,
    )
    db.add(instruction)
    await db.flush()
    version = await _add_version(db, instruction, body=text, user_id=user.id, change_note=change_note)
    _audit(db, user_id=user.id, action="instruction.create", instruction=instruction, details=_facts(version))
    return instruction, version


async def create_draft(
    db: AsyncSession, *, instruction_id: str, body: str, change_note: str, user: User,
) -> InstructionVersion:
    instruction = await load_instruction(db, instruction_id)
    if instruction.status == INSTRUCTION_STATUS_RETIRED:
        raise InstructionRefusal("instruction_retired")
    version = await _add_version(db, instruction, body=_checked_body(body), user_id=user.id, change_note=change_note)
    _audit(db, user_id=user.id, action="instruction.draft", instruction=instruction, details=_facts(version))
    return version


async def retire_instruction(db: AsyncSession, *, instruction_id: str, user: User) -> Instruction:
    instruction = await load_instruction(db, instruction_id)
    if instruction.status == INSTRUCTION_STATUS_RETIRED:
        raise InstructionRefusal("instruction_retired")
    now = utc_now()
    instruction.status, instruction.updated_at = INSTRUCTION_STATUS_RETIRED, now
    for version in (
        await db.execute(select(InstructionVersion).where(InstructionVersion.instruction_id == instruction.id))
    ).scalars():
        if version.state != "retired":
            version.state, version.retired_at = "retired", now
    await db.flush()
    _audit(db, user_id=user.id, action="instruction.retire", instruction=instruction, details={})
    return instruction


async def ensure_default_instructions(db: AsyncSession, *, admin_user: User) -> int:
    """Create each shipped instruction once, published (global, bound to its workflow); never overwrites."""
    created = 0
    for seed in SEEDS:
        exists = (
            await db.execute(
                select(Instruction.id).where(Instruction.key == seed.key, Instruction.scope_type == "global")
            )
        ).first()
        if exists is not None:
            continue
        instruction = Instruction(
            key=seed.key, title=seed.title, scope_type=INSTRUCTION_SCOPE_GLOBAL, scope_id=None,
            binding=INSTRUCTION_BINDING_WORKFLOW, workflow_key=seed.workflow_key, status=INSTRUCTION_STATUS_ACTIVE,
            created_by=admin_user.id,
        )
        db.add(instruction)
        await db.flush()
        await _add_version(db, instruction, body=seed.body, user_id=admin_user.id, change_note="Shipped instruction.",
                           source="seed", state="published")
        created += 1
    return created


__all__ = [
    "create_draft",
    "create_instruction",
    "ensure_default_instructions",
    "retire_instruction",
]
