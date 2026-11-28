"""Entity node upsert with alias-first identity resolution."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import KnowledgeGraphAlias, KnowledgeGraphNode
from ...knowledge_trust import evidence_trust_level
from .aliases import _ensure_aliases, _project_filter, _project_scope, normalize_alias
from .descriptions import _embed_text_for, merge_descriptions


async def _existing_node(
    db: AsyncSession,
    *,
    scope: str,
    project_id: str | None,
    node_type: str,
    node_key: str,
    candidates: set[str],
    resolve_by_alias: bool,
) -> KnowledgeGraphNode | None:
    node: KnowledgeGraphNode | None = None
    if resolve_by_alias and candidates:
        alias_row = (
            await db.execute(
                select(KnowledgeGraphAlias).where(
                    KnowledgeGraphAlias.project_scope == scope,
                    KnowledgeGraphAlias.normalized_alias.in_(candidates),
                )
            )
        ).scalars().first()
        if alias_row is not None:
            node = await db.get(KnowledgeGraphNode, alias_row.node_id)

    if node is None:
        node = (
            await db.execute(
                select(KnowledgeGraphNode).where(
                    _project_filter(KnowledgeGraphNode.project_id, project_id),
                    KnowledgeGraphNode.node_type == node_type,
                    KnowledgeGraphNode.node_key == node_key,
                )
            )
        ).scalars().first()
    return node


def _update_node(
    node: KnowledgeGraphNode,
    *,
    display_name: str,
    description: str,
    properties: dict[str, Any] | None,
    source_refs: list[str] | None,
) -> None:
    if display_name and not node.display_name:
        node.display_name = display_name
    if description:
        node.description = merge_descriptions(node.description or "", description)
    if properties:
        node.properties = {**(node.properties or {}), **properties}
    if source_refs:
        node.source_refs = sorted({*(node.source_refs or []), *source_refs})


async def upsert_node(
    db: AsyncSession,
    *,
    project_id: str | None,
    node_type: str,
    node_key: str,
    display_name: str = "",
    description: str = "",
    aliases: list[str] | None = None,
    trust_level: str = "bronze",
    classification: str = "internal",
    properties: dict[str, Any] | None = None,
    source_refs: list[str] | None = None,
    embed: bool = True,
    resolve_by_alias: bool = True,
) -> KnowledgeGraphNode:
    """Upsert a node, resolving its identity by alias first; ``resolve_by_alias=False`` restricts that to the node
    key."""
    scope = _project_scope(project_id)
    alias_values = [value for value in [node_key, display_name, *(aliases or [])] if str(value or "").strip()]
    candidates = {normalize_alias(value) for value in alias_values if normalize_alias(value)}

    node = await _existing_node(
        db, scope=scope, project_id=project_id, node_type=node_type, node_key=node_key,
        candidates=candidates, resolve_by_alias=resolve_by_alias,
    )
    if node is None:
        node = KnowledgeGraphNode(
            id=str(uuid.uuid4()), project_id=project_id, node_type=node_type, node_key=node_key,
            display_name=display_name or node_key, description=description or "", trust_level=trust_level,
            classification=classification, properties=properties or {}, source_refs=list(source_refs or []),
        )
        db.add(node)
        await db.flush()
    else:
        _update_node(
            node, display_name=display_name, description=description, properties=properties, source_refs=source_refs
        )
    node.trust_level = evidence_trust_level(node.trust_level, node.source_refs)

    await _ensure_aliases(db, node, scope, alias_values)

    if embed and node.description:
        vector = await _embed_text_for(db, f"{node.display_name}. {node.description}".strip())
        if vector is not None:
            for key, value in vector.items():
                setattr(node, key, value)
    await db.flush()
    return node
