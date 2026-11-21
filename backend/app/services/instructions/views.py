"""Read views of Instructions for the admin API and the Workflows page."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentDefinition, Project
from ...models.runtime.instruction import Instruction, InstructionVersion
from .contract import LAYER_BUDGETS, layer_of


def serialize_version(version: InstructionVersion, *, include_body: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": version.id,
        "version": version.version,
        "state": version.state,
        "source": version.source,
        "digest": version.digest,
        "token_estimate": int(version.token_estimate or 0),
        "change_note": version.change_note or "",
        "findings": list(version.findings_json or []),
        "findings_accepted": bool(version.findings_accepted),
        "approval_id": version.approval_id,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }
    if include_body:
        payload["body"] = version.body
    return payload


def serialize_instruction(
    instruction: Instruction, *, scope_name: str | None = None, include_bodies: bool = False,
) -> dict[str, Any]:
    versions = sorted(instruction.versions, key=lambda item: item.version)
    published = next((item for item in versions if item.state == "published"), None)
    latest = versions[-1] if versions else None
    return {
        "id": instruction.id,
        "key": instruction.key,
        "title": instruction.title,
        "scope_type": instruction.scope_type,
        "scope_id": instruction.scope_id,
        "scope_name": scope_name,
        "binding": instruction.binding,
        "workflow_key": instruction.workflow_key,
        "layer": layer_of(instruction),
        "layer_budget": LAYER_BUDGETS[layer_of(instruction)],
        "status": instruction.status,
        "published": serialize_version(published, include_body=include_bodies) if published else None,
        "latest": serialize_version(latest, include_body=include_bodies) if latest else None,
        "versions": [serialize_version(item) for item in versions] if include_bodies else [],
        "updated_at": instruction.updated_at.isoformat() if instruction.updated_at else None,
    }


async def _scope_names(db: AsyncSession, instructions: list[Instruction]) -> dict[str, str]:
    workspace_ids = {item.scope_id for item in instructions if item.scope_type == "workspace" and item.scope_id}
    agent_ids = {item.scope_id for item in instructions if item.scope_type == "agent" and item.scope_id}
    names: dict[str, str] = {}
    if workspace_ids:
        rows = await db.execute(select(Project.id, Project.name).where(Project.id.in_(workspace_ids)))
        names.update({str(ident): str(name) for ident, name in rows.all()})
    if agent_ids:
        query = select(AgentDefinition.id, AgentDefinition.name).where(AgentDefinition.id.in_(agent_ids))
        rows = await db.execute(query)
        names.update({str(ident): str(name) for ident, name in rows.all()})
    return names


async def list_instructions(db: AsyncSession, *, include_retired: bool = False) -> list[dict[str, Any]]:
    query = select(Instruction).options(selectinload(Instruction.versions)).order_by(Instruction.key)
    if not include_retired:
        query = query.where(Instruction.status == "active")
    instructions = list((await db.execute(query)).scalars().all())
    names = await _scope_names(db, instructions)
    return [serialize_instruction(item, scope_name=names.get(str(item.scope_id))) for item in instructions]


async def instruction_detail(db: AsyncSession, instruction_id: str) -> dict[str, Any] | None:
    instruction = (
        await db.execute(
            select(Instruction).options(selectinload(Instruction.versions)).where(Instruction.id == instruction_id)
        )
    ).scalars().first()
    if instruction is None:
        return None
    names = await _scope_names(db, [instruction])
    return serialize_instruction(instruction, scope_name=names.get(str(instruction.scope_id)), include_bodies=True)


async def workflow_instruction_keys(db: AsyncSession) -> dict[str, list[str]]:
    """Published instructions bound to each workflow key (the Workflows page's "Instructions bound")."""
    rows = (
        await db.execute(
            select(Instruction.workflow_key, Instruction.key, InstructionVersion.version)
            .join(InstructionVersion, InstructionVersion.instruction_id == Instruction.id)
            .where(Instruction.status == "active", Instruction.workflow_key.is_not(None),
                   InstructionVersion.state == "published")
        )
    ).all()
    bound: dict[str, list[str]] = {}
    for workflow_key, key, version in rows:
        bound.setdefault(str(workflow_key), []).append(f"{key} v{version}")
    return {key: sorted(value) for key, value in bound.items()}


__all__ = [
    "instruction_detail",
    "list_instructions",
    "serialize_instruction",
    "serialize_version",
    "workflow_instruction_keys",
]
