"""What a turn reads: the published instructions its scope and binding select, in the fixed order.

A turn gets every active instruction with a published version whose scope matches (global, the turn's
Workspace, the turn's agent definition) and whose binding matches (always, or the selected workflow).
No scoring, no keyword hints, no prompt text as input. Order: agent → Workspace (global and Workspace
scope) → workflow, each layer by key. The turn records ``key@version`` with digest and layer.

``instruction_get`` (the model's tool) reads one instruction by exact key, restricted to global and the
active Workspace.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.instruction import (
    INSTRUCTION_BINDING_ALWAYS,
    INSTRUCTION_BINDING_WORKFLOW,
    INSTRUCTION_SCOPE_AGENT,
    INSTRUCTION_SCOPE_GLOBAL,
    INSTRUCTION_SCOPE_WORKSPACE,
    INSTRUCTION_STATUS_ACTIVE,
    Instruction,
    InstructionVersion,
)
from .contract import LAYER_ORDER, layer_of

INSTRUCTIONS_METADATA_KEY = "instructions"
SECTION_HEADING = "## Instructions"
RECORD_FIELDS = ("key", "version", "digest", "layer", "scope_type", "workflow_key", "token_estimate")


def _scope_clause(project_id: str | None, agent_definition_id: str | None):
    clauses = [Instruction.scope_type == INSTRUCTION_SCOPE_GLOBAL]
    if project_id:
        clauses.append(and_(Instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE, Instruction.scope_id == project_id))
    if agent_definition_id:
        clauses.append(
            and_(Instruction.scope_type == INSTRUCTION_SCOPE_AGENT, Instruction.scope_id == agent_definition_id)
        )
    return or_(*clauses)


async def turn_instructions(
    db: AsyncSession, *, project_id: str | None, agent_definition_id: str | None, workflow_key: str | None,
) -> list[dict[str, Any]]:
    binding = Instruction.binding == INSTRUCTION_BINDING_ALWAYS
    if workflow_key:
        binding = or_(binding, and_(Instruction.binding == INSTRUCTION_BINDING_WORKFLOW,
                                    Instruction.workflow_key == workflow_key))
    rows = (
        await db.execute(
            select(Instruction, InstructionVersion)
            .join(InstructionVersion, InstructionVersion.instruction_id == Instruction.id)
            .where(
                Instruction.status == INSTRUCTION_STATUS_ACTIVE,
                InstructionVersion.state == "published",
                _scope_clause(project_id, agent_definition_id),
                binding,
            )
        )
    ).all()
    items = [
        {
            "key": instruction.key,
            "title": instruction.title,
            "version": version.version,
            "digest": version.digest,
            "layer": layer_of(instruction),
            "scope_type": instruction.scope_type,
            "workflow_key": instruction.workflow_key,
            "token_estimate": int(version.token_estimate or 0),
            "body": version.body,
        }
        for instruction, version in rows
    ]
    return sorted(items, key=lambda item: (LAYER_ORDER.index(item["layer"]), item["key"], item["scope_type"]))


def render_instructions_section(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = [SECTION_HEADING]
    for item in items:
        lines.append(f"\n### {item['key']} v{item['version']}")
        lines.append(str(item["body"]).strip())
    return "\n".join(lines)


def instructions_record(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the turn's metadata records: identity only, never the body."""
    return [
        {key: item[key] for key in RECORD_FIELDS}
        for item in items
    ]


async def instruction_get(db: AsyncSession, *, key: str, project_id: str | None) -> dict[str, Any] | None:
    """One published instruction by exact key, global or of the active Workspace (Workspace wins)."""
    rows = (
        await db.execute(
            select(Instruction, InstructionVersion)
            .join(InstructionVersion, InstructionVersion.instruction_id == Instruction.id)
            .where(
                Instruction.key == str(key or "").strip(),
                Instruction.status == INSTRUCTION_STATUS_ACTIVE,
                InstructionVersion.state == "published",
                _scope_clause(project_id, None),
            )
        )
    ).all()
    if not rows:
        return None
    instruction, version = sorted(rows, key=lambda row: row[0].scope_type != INSTRUCTION_SCOPE_WORKSPACE)[0]
    return {"key": instruction.key, "title": instruction.title, "version": version.version, "body": version.body}


async def prepare_turn_instructions(
    db: AsyncSession,
    *,
    session_metadata: dict[str, Any],
    project_id: str | None,
    agent_definition: dict[str, Any] | None,
) -> str:
    """Resolve the turn's instructions, record their identity on the session metadata, return the section."""
    from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY, workflow_selection_from_resolution

    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    selected = workflow_selection_from_resolution(resolution).selected
    workflow_key = str(resolution.get("workflow_key") or "") if selected and isinstance(resolution, dict) else ""
    agent_id = str((agent_definition or {}).get("id") or "") or None
    items = await turn_instructions(
        db, project_id=project_id, agent_definition_id=agent_id, workflow_key=workflow_key or None
    )
    session_metadata[INSTRUCTIONS_METADATA_KEY] = instructions_record(items)
    return render_instructions_section(items)


__all__ = [
    "INSTRUCTIONS_METADATA_KEY",
    "instruction_get",
    "instructions_record",
    "prepare_turn_instructions",
    "render_instructions_section",
    "turn_instructions",
]
