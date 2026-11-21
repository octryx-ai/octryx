"""Agent-facing retrieval helpers for the Engineering Knowledge Graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import CodeRepository, EngineeringKnowledgeGraphNode
from ...time_utils import utc_now
from .graph_store_serializers import serialize_graph_node

ACTIVE_STATUSES = {"active"}
DEFAULT_ALLOWED_CLASSIFICATIONS = ("public", "internal")
DEFAULT_ALLOWED_TRUST_LEVELS = ("gold", "official", "verified")
SILVER_ALLOWED_TRUST_LEVELS = ("silver", *DEFAULT_ALLOWED_TRUST_LEVELS)
TRUST_RANK = {"official": 0, "verified": 1, "gold": 2, "silver": 3, "bronze": 4, "untrusted": 9}
MAX_RESULTS = 25


@dataclass(frozen=True)
class EngineeringKnowledgeVisibility:
    """Policy-normalized visibility controls for agent retrieval."""

    project_ids: tuple[str, ...] = ()
    repository_id: str | None = None
    allowed_classifications: tuple[str, ...] = DEFAULT_ALLOWED_CLASSIFICATIONS
    allowed_trust_levels: tuple[str, ...] = DEFAULT_ALLOWED_TRUST_LEVELS
    include_silver: bool = False


async def search_engineering_knowledge_graph(
    db: AsyncSession,
    *,
    query: str = "",
    node_types: list[str] | None = None,
    repository_id: str | None = None,
    project_ids: list[str] | None = None,
    allowed_classifications: list[str] | None = None,
    include_silver: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    """Return compact, evidence-backed graph facts visible to an agent."""

    visibility = await build_engineering_knowledge_visibility(
        db,
        project_ids=project_ids or [],
        repository_id=repository_id,
        allowed_classifications=allowed_classifications,
        include_silver=include_silver,
    )
    safe_limit = _bounded_limit(limit)
    filters = _visibility_filters(visibility)
    if node_types:
        filters.append(EngineeringKnowledgeGraphNode.node_type.in_([_normalize_type(item) for item in node_types]))
    if query.strip():
        filters.append(_query_filter(query))

    rows = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
                .where(*filters)
                .order_by(
                    EngineeringKnowledgeGraphNode.updated_at.desc(),
                    EngineeringKnowledgeGraphNode.node_type.asc(),
                )
                .limit(min(MAX_RESULTS, safe_limit * 4))
            )
        )
        .scalars()
        .unique()
        .all()
    )
    ranked = sorted(rows, key=lambda node: _rank_node(node, query=query))[:safe_limit]
    return {
        "query": query,
        "count": len(ranked),
        "results": [_compact_node(node, query=query) for node in ranked],
        "policy": {
            "visible_scope_keys": _visible_scope_keys(visibility),
            "allowed_classifications": list(visibility.allowed_classifications),
            "allowed_trust_levels": list(visibility.allowed_trust_levels),
            "include_silver": visibility.include_silver,
            "excluded_statuses": ["draft", "rejected", "retracted", "expired", "stale"],
            "content": "compact_evidence_backed_facts",
        },
    }


async def build_engineering_knowledge_visibility(
    db: AsyncSession,
    *,
    project_ids: list[str],
    repository_id: str | None,
    allowed_classifications: list[str] | None,
    include_silver: bool,
) -> EngineeringKnowledgeVisibility:
    safe_project_ids = tuple(sorted({item.strip() for item in project_ids if str(item or "").strip()}))
    safe_repository_id = str(repository_id or "").strip() or None
    if safe_repository_id:
        repo = await db.get(CodeRepository, safe_repository_id)
        if repo is None or not repo.is_active:
            safe_repository_id = None
        elif repo.project_id and repo.project_id not in safe_project_ids:
            safe_repository_id = None

    safe_classifications = tuple(
        item
        for item in (_normalize_type(value) for value in (allowed_classifications or DEFAULT_ALLOWED_CLASSIFICATIONS))
        if item in DEFAULT_ALLOWED_CLASSIFICATIONS
    ) or DEFAULT_ALLOWED_CLASSIFICATIONS
    allowed_trust = SILVER_ALLOWED_TRUST_LEVELS if include_silver else DEFAULT_ALLOWED_TRUST_LEVELS
    return EngineeringKnowledgeVisibility(
        project_ids=safe_project_ids,
        repository_id=safe_repository_id,
        allowed_classifications=safe_classifications,
        allowed_trust_levels=allowed_trust,
        include_silver=include_silver,
    )


def engineering_knowledge_policy_from_project_config(project_config: dict[str, Any] | None) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    raw_policy = config.get("engineering_knowledge_policy")
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    return {
        "include_silver": bool(policy.get("include_silver")),
        "allowed_classifications": [
            str(value).strip().lower()
            for value in (policy.get("allowed_classifications") or DEFAULT_ALLOWED_CLASSIFICATIONS)
            if str(value).strip()
        ],
    }


def _visibility_filters(visibility: EngineeringKnowledgeVisibility) -> list[Any]:
    now = utc_now()
    scope_keys = _visible_scope_keys(visibility)
    return [
        EngineeringKnowledgeGraphNode.scope_key.in_(scope_keys),
        EngineeringKnowledgeGraphNode.status.in_(ACTIVE_STATUSES),
        EngineeringKnowledgeGraphNode.trust_level.in_(visibility.allowed_trust_levels),
        EngineeringKnowledgeGraphNode.classification.in_(visibility.allowed_classifications),
        or_(
            EngineeringKnowledgeGraphNode.valid_from.is_(None),
            EngineeringKnowledgeGraphNode.valid_from <= now,
        ),
        or_(
            EngineeringKnowledgeGraphNode.valid_until.is_(None),
            EngineeringKnowledgeGraphNode.valid_until > now,
        ),
    ]


def _visible_scope_keys(visibility: EngineeringKnowledgeVisibility) -> list[str]:
    scope_keys = ["global:global"]
    for project_id in visibility.project_ids:
        scope_keys.append(f"project:{project_id}")
        scope_keys.append(f"workspace:{project_id}")
    if visibility.repository_id:
        scope_keys.append(f"repository:{visibility.repository_id}")
    return sorted(set(scope_keys))


def _query_filter(query: str) -> Any:
    needle = f"%{query.strip().lower()}%"
    return or_(
        func.lower(EngineeringKnowledgeGraphNode.node_key).like(needle),
        func.lower(EngineeringKnowledgeGraphNode.display_name).like(needle),
        func.lower(EngineeringKnowledgeGraphNode.summary).like(needle),
        func.lower(cast(EngineeringKnowledgeGraphNode.properties_json, String)).like(needle),
        func.lower(cast(EngineeringKnowledgeGraphNode.source_refs_json, String)).like(needle),
    )


def _rank_node(node: EngineeringKnowledgeGraphNode, *, query: str) -> tuple[int, int, str]:
    text = " ".join([node.node_key or "", node.display_name or "", node.summary or ""]).lower()
    needle = query.strip().lower()
    query_rank = 0 if needle and needle in text else 1
    return (TRUST_RANK.get(node.trust_level, 8), query_rank, node.display_name or node.node_key)


def _compact_node(node: EngineeringKnowledgeGraphNode, *, query: str) -> dict[str, Any]:
    payload = serialize_graph_node(node)
    federation = _compact_federation_origin(payload["properties"])
    return {
        "id": payload["id"],
        "node_type": payload["node_type"],
        "node_key": payload["node_key"],
        "display_name": payload["display_name"],
        "summary": _trim(payload["summary"], 900),
        "trust_level": payload["trust_level"],
        "classification": payload["classification"],
        "scope_type": payload["scope_type"],
        "scope_id": payload["scope_id"],
        "repository_id": payload["repository_id"],
        "valid_from": payload["valid_from"],
        "valid_until": payload["valid_until"],
        "freshness": "valid",
        "evidence": _compact_source_refs(payload["source_refs"]),
        "matched_query": query,
        "properties": _compact_properties(payload["properties"]),
        "origin": "imported" if federation else "local",
        "federation": federation,
    }


def _compact_federation_origin(properties: dict[str, Any]) -> dict[str, Any] | None:
    federation = properties.get("federation") if isinstance(properties, dict) else None
    if not isinstance(federation, dict) or federation.get("origin") != "imported":
        return None
    return {
        "origin": "imported",
        "publisher_instance_id": federation.get("publisher_instance_id"),
        "package_id": federation.get("package_id"),
        "original_trust_level": federation.get("original_trust_level"),
        "local_trust_level": federation.get("local_trust_level"),
        "import_status": federation.get("import_status"),
        "mapped_local_entity_id": federation.get("mapped_local_entity_id"),
    }


def _compact_source_refs(source_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for ref in source_refs[:5]:
        compact.append(
            {
                "source_type": ref.get("source_type"),
                "source_ref": ref.get("source_ref"),
                "title": _trim(ref.get("title"), 220),
                "url": ref.get("url"),
                "observed_at": ref.get("observed_at"),
            }
        )
    return compact


def _compact_properties(properties: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "affected_package",
        "build_system",
        "cve",
        "language",
        "pipeline",
        "repository",
        "reviewer",
        "severity",
        "stack",
        "technology",
        "version",
    }
    return {key: value for key, value in properties.items() if key in allowed_keys}


def _bounded_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, MAX_RESULTS))


def _normalize_type(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _trim(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."
