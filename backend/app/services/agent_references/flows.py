"""Workflows (flow definitions) whose stored versions reference one agent.

A workflow version references an agent through a node whose registry contract
declares ``config.agent_definition_id`` (today ``agent_step`` and ``supervisor``);
``definition_json.nodes`` is a flat list, parallel branches are ordinary nodes
joined by edges. Archived workflows (``is_active`` false) are skipped: they can
neither run nor receive drafts, and the workflow list hides them by default.

The scan is bounded: a text prefilter on the stored JSON selects candidate
workflows (newest first, at most ``limit + 1``), and every candidate is then
checked exactly against its node configs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, cast, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import FlowDefinition, FlowDefinitionVersion
from ..flow_node_registry import FLOW_NODE_CONTRACTS
from .states import CURRENT_DRAFT, OLDER_REVISION_ONLY, PUBLISHED, Reference, reference_from

AGENT_CONFIG_KEY = "agent_definition_id"
AGENT_NODE_TYPES: frozenset[str] = frozenset(
    contract.type
    for contract in FLOW_NODE_CONTRACTS
    if AGENT_CONFIG_KEY in (contract.config_schema.get("properties") or {})
)


def definition_references_agent(definition: Any, agent_id: str) -> bool:
    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict) or node.get("type") not in AGENT_NODE_TYPES:
            continue
        config = node.get("config")
        if isinstance(config, dict) and str(config.get(AGENT_CONFIG_KEY) or "").strip() == agent_id:
            return True
    return False


def version_state(flow: FlowDefinition, version: FlowDefinitionVersion, latest_number: int) -> str:
    if version.id == flow.current_version_id and version.status == "published" and flow.status == "published":
        return PUBLISHED
    if version.version == latest_number and version.status == "draft":
        return CURRENT_DRAFT
    return OLDER_REVISION_ONLY


def flow_reference(flow: FlowDefinition, agent_id: str) -> Reference | None:
    """The most significant referencing version (and the latest version the editor opens), or None."""
    versions = list(flow.versions or [])
    if not versions:
        return None
    latest_number = max(int(version.version) for version in versions)
    candidates = [
        (version_state(flow, version, latest_number), int(version.version))
        for version in versions
        if definition_references_agent(version.definition_json, agent_id)
    ]
    return reference_from(candidates, latest_number)


async def flow_references(
    db: AsyncSession, *, agent_id: str, limit: int
) -> tuple[list[tuple[FlowDefinition, Reference]], bool]:
    """Return ``([(flow, reference)], truncated)`` for active workflows, newest first."""
    mentions = exists().where(
        FlowDefinitionVersion.flow_id == FlowDefinition.id,
        cast(FlowDefinitionVersion.definition_json, Text).contains(agent_id, autoescape=True),
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
        reference = flow_reference(flow, agent_id)
        if reference is not None:
            found.append((flow, reference))
    return found, truncated


__all__ = ["AGENT_CONFIG_KEY", "AGENT_NODE_TYPES", "definition_references_agent", "flow_references", "version_state"]
