"""Build the execution payload of a resolved Agent Definition, live or published."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinition, AgentGroup
from .agent_definition_execution_states import (
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    SOURCE_LIVE_DRAFT_ROW,
    SOURCE_PUBLISHED_REVISION,
    STATUS_NEEDS_PUBLICATION,
    STATUS_RESOLVED,
    AgentDefinitionResolution,
)
from .agent_definition_payload import (
    build_agent_execution_prompt,
    payload_from_snapshot,
    serialize_agent_definition_payload,
)
from .agent_definition_revision_store import get_published_revision
from .agent_definition_snapshot import snapshot_header, snapshot_steps
from .prompt_catalog import PROMPT_TEMPLATES_TRACE_KEY, prompt_set_scope, resolve_prompt_set

# Logged under the facade's name so log filters and handlers set up for resolution keep matching.
logger = logging.getLogger("app.services.agent_definition_execution")


async def resolve_live(db: AsyncSession, *, definition: AgentDefinition, mode: str) -> AgentDefinitionResolution:
    payload = serialize_agent_definition_payload(definition)
    resolution = AgentDefinitionResolution(
        definition_id=definition.id,
        mode=mode,
        status=STATUS_RESOLVED,
        source=SOURCE_LIVE_DRAFT_ROW,
        payload=payload,
    )
    await _finish_payload(db, payload, resolution)
    return resolution


async def resolve_published(
    db: AsyncSession, *, definition: AgentDefinition, mode: str
) -> AgentDefinitionResolution:
    revision = await get_published_revision(db, definition.id)
    if revision is None:
        logger.info(
            "agent definition %s has no published revision; refusing execution in %s mode",
            definition.id,
            mode,
        )
        return AgentDefinitionResolution(
            definition_id=definition.id, mode=mode, status=STATUS_NEEDS_PUBLICATION
        )

    snapshot = revision.snapshot
    header = snapshot_header(snapshot)
    payload = payload_from_snapshot(
        header,
        snapshot_steps(snapshot),
        definition_id=definition.id,
        group_name=await _group_label(db, definition=definition, header=header),
        live_step_ids_by_position={
            int(step.position or 0): step.id for step in definition.steps
        },
        builtin_key=definition.builtin_key or "",
    )
    resolution = AgentDefinitionResolution(
        definition_id=definition.id,
        mode=mode,
        status=STATUS_RESOLVED,
        source=SOURCE_PUBLISHED_REVISION,
        revision_id=revision.id,
        revision_number=int(revision.revision_number),
        checksum=revision.checksum,
        payload=payload,
    )
    await _finish_payload(db, payload, resolution)
    return resolution


async def _group_label(
    db: AsyncSession, *, definition: AgentDefinition, header: dict[str, Any]
) -> str:
    # An unknown group yields an empty label rather than a guess.
    snapshot_group_id = str(header.get("group_id") or "").strip()
    if not snapshot_group_id:
        return ""
    group = getattr(definition, "group", None)
    if group is not None and str(group.id) == snapshot_group_id:
        return str(group.name or "")
    name = (
        await db.execute(select(AgentGroup.name).where(AgentGroup.id == snapshot_group_id))
    ).scalar_one_or_none()
    return str(name or "")


async def _finish_payload(db: AsyncSession, payload: dict[str, Any], resolution: AgentDefinitionResolution) -> None:
    # The provenance keys are additive: no other key changes meaning.
    prompt_set = await resolve_prompt_set(
        db,
        workspace_id=str(payload.get("projectId") or "").strip() or None,
    )
    with prompt_set_scope(prompt_set):
        payload["prompt"] = build_agent_execution_prompt(payload)
    payload[PROMPT_TEMPLATES_TRACE_KEY] = prompt_set.usage()
    payload[PAYLOAD_MODE_KEY] = resolution.mode
    payload[PAYLOAD_SOURCE_KEY] = resolution.source
    payload[PAYLOAD_REVISION_ID_KEY] = resolution.revision_id
    payload[PAYLOAD_REVISION_NUMBER_KEY] = resolution.revision_number

