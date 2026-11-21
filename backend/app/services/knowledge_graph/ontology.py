"""Ontology: the entity and relation types the extractor is allowed to produce.

A curated, deterministic default set is the backbone. A project may override it
via ``project.config['knowledge_ontology']`` (a governed, reviewable override —
LLM prompt auto-tuning proposals feed into this rather than mutating it directly).
"""

from __future__ import annotations

from typing import Any

DEFAULT_ENTITY_TYPES: tuple[str, ...] = (
    "person",
    "team",
    "service",
    "component",
    "system",
    "product",
    "repository",
    "module",
    "resource",
    "database",
    "table",
    "endpoint",
    "incident",
    "change",
    "ticket",
    "document",
    "concept",
)

DEFAULT_RELATION_TYPES: tuple[str, ...] = (
    "assigned_to",
    "owns",
    "depends_on",
    "documents",
    "deploys_to",
    "part_of",
    "contains",
    "references",
    "imports",
    "authored",
    "contributed_to",
    "affects",
    "resolves",
    "mentions",
    "relates_to",
)


def resolve_ontology(project: Any = None) -> dict[str, list[str]]:
    entity_types = list(DEFAULT_ENTITY_TYPES)
    relation_types = list(DEFAULT_RELATION_TYPES)
    config = getattr(project, "config", None) if project is not None else None
    override = (config or {}).get("knowledge_ontology") if isinstance(config, dict) else None
    if isinstance(override, dict):
        entities = override.get("entity_types")
        relations = override.get("relation_types")
        if isinstance(entities, list) and entities:
            entity_types = [str(item).strip().lower() for item in entities if str(item).strip()]
        if isinstance(relations, list) and relations:
            relation_types = [str(item).strip().lower() for item in relations if str(item).strip()]
    return {"entity_types": entity_types, "relation_types": relation_types}


async def resolve_active_ontology(
    db: Any, *, project_id: str | None = None, project: Any = None
) -> dict[str, list[str]]:
    """Resolve the ontology, preferring the ACTIVE versioned row for the scope.

    Order: active `knowledge_ontology_versions` row → project config override →
    curated defaults. Draft versions (e.g. auto-tuning proposals) are ignored
    until explicitly activated — the review gate.
    """
    from sqlalchemy import select

    from ...models import KnowledgeOntologyVersion

    scope = project_id or ""
    row = (
        (
            await db.execute(
                select(KnowledgeOntologyVersion)
                .where(
                    KnowledgeOntologyVersion.project_scope == scope,
                    KnowledgeOntologyVersion.status == "active",
                )
                .order_by(KnowledgeOntologyVersion.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if row is not None:
        entities = [str(item).strip().lower() for item in (row.entity_types or []) if str(item).strip()]
        relations = [str(item).strip().lower() for item in (row.relation_types or []) if str(item).strip()]
        if entities and relations:
            return {"entity_types": entities, "relation_types": relations}
    return resolve_ontology(project)
