"""Workflows whose stored versions name one agent: a phase names its platform agent (``config.agent``, the agent's
builtin key)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, cast, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import FlowDefinition, FlowDefinitionVersion
from ..workflow_runs.phase_agents import AGENT_KEY
from .states import CURRENT_DRAFT, OLDER_REVISION_ONLY, PUBLISHED, Reference, reference_from

AGENT_NODE_TYPES: frozenset[str] = frozenset({"phase"})


def definition_references_agent(definition: Any, agent_key: str) -> bool:
    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict) or node.get("type") not in AGENT_NODE_TYPES:
            continue
        config = node.get("config")
        if isinstance(config, dict) and str(config.get(AGENT_KEY) or "").strip() == agent_key:
            return True
    return False


def version_state(flow: FlowDefinition, version: FlowDefinitionVersion, latest_number: int) -> str:
    if version.id == flow.current_version_id and version.status == "published" and flow.status == "published":
        return PUBLISHED
    if version.version == latest_number and version.status == "draft":
        return CURRENT_DRAFT
    return OLDER_REVISION_ONLY


def flow_reference(flow: FlowDefinition, agent_key: str) -> Reference | None:
    versions = list(flow.versions or [])
    if not versions:
        return None
    latest_number = max(int(version.version) for version in versions)
    candidates = [
        (version_state(flow, version, latest_number), int(version.version))
        for version in versions
        if definition_references_agent(version.definition_json, agent_key)
    ]
    return reference_from(candidates, latest_number)


async def flow_references(
    db: AsyncSession, *, agent_key: str, limit: int
) -> tuple[list[tuple[FlowDefinition, Reference]], bool]:
    mentions = exists().where(
        FlowDefinitionVersion.flow_id == FlowDefinition.id,
        cast(FlowDefinitionVersion.definition_json, Text).contains(agent_key, autoescape=True),
    )
    stmt = (
        select(FlowDefinition)
        .where(FlowDefinition.is_active.is_(True), mentions)
        .options(selectinload(FlowDefinition.versions))
        .order_by(FlowDefinition.updated_at.desc(), FlowDefinition.id.asc())
        .limit(limit + 1)
    )
    candidates = list((await db.execute(stmt)).scalars())
    truncated = len(candidates) > limit
    found: list[tuple[FlowDefinition, Reference]] = []
    for flow in candidates[:limit]:
        reference = flow_reference(flow, agent_key)
        if reference is not None:
            found.append((flow, reference))
    return found, truncated


__all__ = ["AGENT_NODE_TYPES", "definition_references_agent", "flow_references", "version_state"]
