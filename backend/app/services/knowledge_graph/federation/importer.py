"""Verify and import a package as instance-global federated knowledge."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_graph import KnowledgeClaim, KnowledgeGraphAlias, KnowledgeGraphNode
from ..store import add_claim, upsert_edge, upsert_node
from .package import FEDERATED_TRUST_LEVEL, _node_ref, verify_entity_graph_package


async def _import_node(db: AsyncSession, entry: dict[str, Any], source_ref: str) -> tuple[str, Any, bool] | None:
    node_type = str(entry.get("node_type") or "").strip().lower()
    node_key = str(entry.get("node_key") or "").strip()
    if not node_type or not node_key:
        return None
    aliases = [str(a) for a in (entry.get("aliases") or []) if str(a).strip()]
    # Cross-scope identity: when an alias already belongs to a LOCAL node
    # (project-scoped or global), the federated entity merges into it —
    # a hub directory entry for a person must never duplicate the team's
    # own node. Without a match, the entity lands instance-global.
    existed, target_project_id = await _resolve_target_scope(
        db, node_type=node_type, node_key=node_key, aliases=aliases
    )
    node = await upsert_node(
        db,
        project_id=target_project_id,
        node_type=node_type,
        node_key=node_key,
        display_name=str(entry.get("display_name") or node_key),
        description=str(entry.get("description") or ""),
        aliases=aliases,
        trust_level=FEDERATED_TRUST_LEVEL,
        classification=str(entry.get("classification") or "internal"),
        properties=dict(entry.get("properties") or {}),
        source_refs=[source_ref],
    )
    return _node_ref(node_type, node_key), node, existed


async def _import_claims(db: AsyncSession, node: Any, claims: list[Any], source_ref: str) -> int:
    added = 0
    existing_statements = {
        statement.lower()
        for statement in (
            await db.execute(
                select(KnowledgeClaim.statement).where(KnowledgeClaim.subject_node_id == node.id)
            )
        )
        .scalars()
        .all()
    }
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        statement = str(claim.get("statement") or "").strip()
        if not statement or statement.lower() in existing_statements:
            continue
        existing_statements.add(statement.lower())
        await add_claim(
            db,
            project_id=None,
            subject_node_id=node.id,
            statement=statement,
            claim_type=str(claim.get("claim_type") or "fact"),
            valid_from_label=claim.get("valid_from_label"),
            valid_until_label=claim.get("valid_until_label"),
            source_refs=[source_ref],
        )
        added += 1
    return added


async def _import_edges(db: AsyncSession, edges: list[Any], node_by_ref: dict[str, Any], source_ref: str) -> int:
    upserted = 0
    for entry in edges:
        if not isinstance(entry, dict):
            continue
        source = node_by_ref.get(str(entry.get("source") or ""))
        target = node_by_ref.get(str(entry.get("target") or ""))
        edge_type = str(entry.get("edge_type") or "").strip().lower()
        if source is None or target is None or not edge_type:
            continue
        await upsert_edge(
            db,
            project_id=None,
            edge_type=edge_type,
            source_node_id=source.id,
            target_node_id=target.id,
            description=str(entry.get("description") or ""),
            source_refs=[source_ref],
            trust_level=FEDERATED_TRUST_LEVEL,
        )
        upserted += 1
    return upserted


async def import_entity_graph_package(
    db: AsyncSession,
    package: dict[str, Any],
    *,
    signing_key: str,
) -> dict[str, Any]:
    """Verify and import a package as instance-global federated knowledge. An alias already known locally merges, never
    duplicates."""
    verify_entity_graph_package(package, signing_key=signing_key)
    source_instance = str(package.get("source_instance") or "unknown")
    source_ref = f"federated:{source_instance}"

    created = merged = claims_added = 0
    node_by_ref: dict[str, Any] = {}
    for entry in package.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        imported = await _import_node(db, entry, source_ref)
        if imported is None:
            continue
        ref, node, existed = imported
        node_by_ref[ref] = node
        if existed:
            merged += 1
        else:
            created += 1
        claims_added += await _import_claims(db, node, entry.get("claims") or [], source_ref)

    edges_upserted = await _import_edges(db, package.get("edges") or [], node_by_ref, source_ref)

    return {
        "source_instance": source_instance,
        "nodes_created": created,
        "nodes_merged": merged,
        "claims_added": claims_added,
        "edges_upserted": edges_upserted,
    }


async def _resolve_target_scope(
    db: AsyncSession, *, node_type: str, node_key: str, aliases: list[str]
) -> tuple[bool, str | None]:
    """Resolve a package entry against ALL local scopes."""
    from ..store import normalize_alias

    candidates = {normalize_alias(value) for value in [node_key, *aliases] if normalize_alias(value)}
    matches: list[KnowledgeGraphNode] = []
    if candidates:
        node_ids = (
            (
                await db.execute(
                    select(KnowledgeGraphAlias.node_id).where(
                        KnowledgeGraphAlias.normalized_alias.in_(candidates)
                    )
                )
            )
            .scalars()
            .all()
        )
        if node_ids:
            matches = list(
                (
                    await db.execute(
                        select(KnowledgeGraphNode).where(
                            KnowledgeGraphNode.id.in_(set(node_ids)),
                            KnowledgeGraphNode.status == "active",
                        )
                    )
                )
                .scalars()
                .all()
            )
    if not matches:
        by_key = (
            await db.execute(
                select(KnowledgeGraphNode)
                .where(
                    KnowledgeGraphNode.node_type == node_type,
                    KnowledgeGraphNode.node_key == node_key,
                    KnowledgeGraphNode.status == "active",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if by_key is not None:
            matches = [by_key]
    if not matches:
        return False, None
    matches.sort(key=lambda node: ((node.project_id is not None), (node.created_at is None), node.created_at, node.id))
    return True, matches[0].project_id
