"""Configured settings against documented parameters, and settings against each other. All rules are exact and
case-sensitive; nothing is matched by similarity."""

from __future__ import annotations

from sqlalchemy import select

from ....models.project.knowledge_structured import KnowledgeStructuredNode
from .config_families import NodeRow, Placeholders, families
from .config_linkage_compute import compute_linkage
from .config_linkage_rules import _inconsistencies
from .profile_types import LAYER_CONFIGURATION, LAYER_MANUAL
from .store import sync_linkage


async def load_nodes(db, project_id: str, profile_id: str, layer: str, node_types: tuple[str, ...]) -> list[NodeRow]:
    rows = await db.execute(
        select(
            KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.node_type, KnowledgeStructuredNode.revision_id,
            KnowledgeStructuredNode.span_ordinal, KnowledgeStructuredNode.line, KnowledgeStructuredNode.label,
            KnowledgeStructuredNode.properties,
        )
        .where(
            KnowledgeStructuredNode.project_id == project_id,
            KnowledgeStructuredNode.profile == profile_id,
            KnowledgeStructuredNode.layer == layer,
            KnowledgeStructuredNode.node_type.in_(node_types),
        )
        .order_by(KnowledgeStructuredNode.node_id, KnowledgeStructuredNode.revision_id)
    )
    return [NodeRow(str(r[0]), r[1], str(r[2]), r[3], r[4], r[5], dict(r[6] or {})) for r in rows.all()]


async def link_configuration(context) -> dict:
    profile_id = context.profile.profile_id
    settings = await load_nodes(
        context.db, context.project_id, profile_id, LAYER_CONFIGURATION, ("ConfiguredSetting",)
    )
    parameters = await load_nodes(context.db, context.project_id, profile_id, LAYER_MANUAL, ("Parameter",))
    documents = await load_nodes(context.db, context.project_id, profile_id, LAYER_MANUAL, ("Document",))
    profile = context.profile
    placeholders = Placeholders(settings, profile.placeholder_pattern, profile.placeholder_sources)
    if parameters:
        desired = compute_linkage(settings, parameters, documents, profile.registry_sections, placeholders,
                                  profile.non_comparable_defaults, profile.fold_resolved_definitions)
    else:
        resolved = {setting.node_id: placeholders.resolve(setting) for setting in settings}
        folded = placeholders.definitions if profile.fold_resolved_definitions else frozenset()
        desired = _inconsistencies(families(settings), resolved, folded)
    counts = await sync_linkage(
        context.db, project_id=context.project_id, layer=LAYER_CONFIGURATION, profile_id=profile_id, desired=desired
    )
    by_type: dict[str, int] = {}
    for edge in desired:
        by_type[edge.edge_type] = by_type.get(edge.edge_type, 0) + 1
    return {
        "state": "ok" if parameters else "no_manual_parameters", "settings": len(settings),
        "parameters": len(parameters), "edges": dict(sorted(by_type.items())), "added": counts.edges,
        "removed": counts.removed_edges,
    }


__all__ = [
    "link_configuration",
    "load_nodes",
]
