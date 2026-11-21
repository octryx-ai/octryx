"""Conflict detection between imported knowledge packages and local graph facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import EngineeringKnowledgeGraphNode
from ...time_utils import utc_now
from .graph_store_serializers import serialize_graph_node


async def classify_federation_import_conflicts(
    db: AsyncSession,
    package: dict[str, Any],
    *,
    base_conflicts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic conflicts between an imported package and local graph facts."""

    conflicts = [_normalized_conflict(item) for item in base_conflicts or [] if isinstance(item, dict)]
    for fact in _package_node_facts(package):
        local = await _find_local_node(db, fact)
        if local is not None:
            conflicts.extend(_local_fact_conflicts(local, fact))
        if _is_stale_fact(package, fact):
            conflicts.append(_conflict(fact, "stale_package", "Package or fact validity has expired"))
    return _deduplicate_conflicts(conflicts)


def _local_fact_conflicts(local: EngineeringKnowledgeGraphNode, fact: dict[str, Any]) -> list[dict[str, Any]]:
    local_payload = serialize_graph_node(local)
    conflicts: list[dict[str, Any]] = []
    if str(local_payload.get("summary") or "") != str(fact.get("summary") or ""):
        conflicts.append(_conflict(fact, "content_differs", "Local fact content differs from imported fact", local))
    if _value(local_payload["properties"], "version") != _value(fact.get("properties"), "version"):
        if _value(local_payload["properties"], "version") or _value(fact.get("properties"), "version"):
            conflicts.append(_conflict(fact, "version_conflict", "Version metadata differs from local fact", local))
    if _value(local_payload["properties"], "baseline") != _value(fact.get("properties"), "baseline"):
        if _value(local_payload["properties"], "baseline") or _value(fact.get("properties"), "baseline"):
            conflicts.append(
                _conflict(fact, "incompatible_baseline", "Baseline metadata differs from local fact", local)
            )
    if _vulnerability_disagrees(local_payload, fact):
        conflicts.append(
            _conflict(fact, "vulnerability_fix_disagreement", "Vulnerability fix guidance differs locally", local)
        )
    return conflicts


def _vulnerability_disagrees(local: dict[str, Any], fact: dict[str, Any]) -> bool:
    local_cve = _value(local.get("properties"), "cve")
    imported_cve = _value(fact.get("properties"), "cve")
    local_fix = _value(local.get("properties"), "fix") or local.get("summary")
    imported_fix = _value(fact.get("properties"), "fix") or fact.get("summary")
    fix_differs = bool(local_fix and imported_fix and str(local_fix).strip() != str(imported_fix).strip())
    if fact.get("type") in {"fix_pattern", "vulnerability"} and fix_differs:
        return True
    if not local_cve or not imported_cve or local_cve != imported_cve:
        return False
    return fix_differs


async def _find_local_node(db: AsyncSession, fact: dict[str, Any]) -> EngineeringKnowledgeGraphNode | None:
    key = str(fact.get("key") or "").strip()
    node_type = str(fact.get("type") or "").strip()
    scope_key = str(fact.get("scope_key") or "global:global").strip() or "global:global"
    if not key or not node_type:
        return None
    return (
        await db.execute(
            select(EngineeringKnowledgeGraphNode)
            .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
            .where(
                EngineeringKnowledgeGraphNode.scope_key == scope_key,
                EngineeringKnowledgeGraphNode.node_type == node_type,
                EngineeringKnowledgeGraphNode.node_key == key,
            )
        )
    ).scalar_one_or_none()


def _package_node_facts(package: dict[str, Any]) -> list[dict[str, Any]]:
    facts = dict(package.get("facts") or {})
    return [dict(item) for item in facts.get("nodes") or [] if isinstance(item, dict)]


def _is_stale_fact(package: dict[str, Any], fact: dict[str, Any]) -> bool:
    valid_until = _parse_datetime(fact.get("valid_until")) or _parse_datetime(package.get("valid_until"))
    return bool(valid_until and valid_until <= utc_now())


def _conflict(
    fact: dict[str, Any],
    conflict: str,
    reason: str,
    local: EngineeringKnowledgeGraphNode | None = None,
) -> dict[str, Any]:
    return {
        "conflict": conflict,
        "reason": reason,
        "node_key": fact.get("key"),
        "node_type": fact.get("type"),
        "local_node_id": local.id if local else None,
        "severity": "high" if conflict in {"vulnerability_fix_disagreement", "incompatible_baseline"} else "medium",
    }


def _normalized_conflict(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "conflict": str(item.get("conflict") or "content_differs"),
        "reason": str(item.get("reason") or item.get("message") or item.get("conflict") or "Conflict detected"),
        "node_key": item.get("node_key"),
        "node_type": item.get("node_type"),
        "local_node_id": item.get("node_id") or item.get("local_node_id"),
        "severity": item.get("severity") or "medium",
    }


def _deduplicate_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in conflicts:
        key = (str(item.get("conflict")), str(item.get("node_key")), str(item.get("local_node_id")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _value(payload: Any, key: str) -> Any:
    return dict(payload or {}).get(key) if isinstance(payload, dict) else None

