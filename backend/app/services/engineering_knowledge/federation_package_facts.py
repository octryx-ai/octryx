"""Turn reviewed graph nodes and edges into export-controlled package facts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ...models import EngineeringKnowledgeGraphEdge, EngineeringKnowledgeGraphNode
from ...time_utils import utc_now
from .federation_export_control import apply_federation_export_control_to_fact
from .federation_package_common import (
    PACKAGE_SCHEMA_VERSION,
    KnowledgePackageValidationError,
    _fact_content_digest,
    _reject_unsafe_payload,
)
from .graph_store_serializers import serialize_graph_edge, serialize_graph_node


def _unsigned_package(
    *,
    nodes: list[EngineeringKnowledgeGraphNode],
    edges: list[EngineeringKnowledgeGraphEdge],
    publisher_instance_id: str,
    package_id: str | None,
    usage_policy: dict[str, Any] | None,
    compatibility: dict[str, Any] | None,
    redaction: dict[str, Any] | None,
    retractions: list[dict[str, Any]] | None,
    valid_from: datetime | None,
    valid_until: datetime | None,
    allowed_classifications: set[str],
    allowed_trust_levels: set[str],
    export_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    publisher = str(publisher_instance_id or "").strip()
    if not publisher:
        raise KnowledgePackageValidationError("publisher_instance_id is required")
    package_nodes, package_edges = _package_facts(
        nodes,
        edges,
        allowed_classifications=allowed_classifications,
        allowed_trust_levels=allowed_trust_levels,
        export_policy=export_policy,
    )
    classification = _package_classification(package_nodes, package_edges)
    trust_level = _package_trust_level(package_nodes, package_edges)
    now = utc_now()
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id or str(uuid.uuid4()),
        "publisher": {"instance_id": publisher},
        "created_at": now.isoformat(),
        "valid_from": (valid_from or now).isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
        "classification": classification,
        "trust_level": trust_level,
        "usage_policy": dict(usage_policy or {"allowed_use": "engineering_agent_context", "redistribution": "review"}),
        "compatibility": {
            "min_schema_version": PACKAGE_SCHEMA_VERSION,
            "content_kind": "engineering_knowledge_graph",
            **dict(compatibility or {}),
        },
        "provenance": {
            "source": "engineering_knowledge_graph",
            "node_count": len(package_nodes),
            "edge_count": len(package_edges),
        },
        "redaction": _redaction_summary(package_nodes, package_edges, redaction),
        "retractions": list(retractions or []),
        "facts": {"nodes": package_nodes, "edges": package_edges},
    }


def _package_facts(
    nodes: list[EngineeringKnowledgeGraphNode],
    edges: list[EngineeringKnowledgeGraphEdge],
    *,
    allowed_classifications: set[str],
    allowed_trust_levels: set[str],
    export_policy: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    package_nodes = [
        _package_node(
            node,
            allowed_classifications=allowed_classifications,
            allowed_trust_levels=allowed_trust_levels,
            export_policy=export_policy,
        )
        for node in nodes
    ]
    package_edges = [
        _package_edge(
            edge,
            allowed_classifications=allowed_classifications,
            allowed_trust_levels=allowed_trust_levels,
            export_policy=export_policy,
        )
        for edge in edges
    ]
    return package_nodes, package_edges


def _redaction_summary(
    package_nodes: list[dict[str, Any]],
    package_edges: list[dict[str, Any]],
    redaction: dict[str, Any] | None,
) -> dict[str, Any]:
    decisions = [
        dict(item.get("export_control") or {})
        for item in [*package_nodes, *package_edges]
        if isinstance(item.get("export_control"), dict)
    ]
    return {
        "raw_content_included": False,
        "sensitive_field_scan": "blocked_on_match",
        "policy_engine": "federation_export_control.v1",
        "redacted_fact_count": len([item for item in decisions if item.get("action") == "redacted"]),
        "decision_count": len(decisions),
        **dict(redaction or {}),
    }


def _package_node(
    node: EngineeringKnowledgeGraphNode,
    *,
    allowed_classifications: set[str],
    allowed_trust_levels: set[str],
    export_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    if node.status != "active":
        raise KnowledgePackageValidationError(f"Only active facts can be exported: {node.node_key}")
    if node.trust_level not in allowed_trust_levels:
        raise KnowledgePackageValidationError(f"Node {node.node_key} has non-exportable trust level")
    payload = serialize_graph_node(node)
    fact = _fact_payload(payload, fact_kind="node")
    return _apply_export_control(
        fact,
        item_label=f"Node {node.node_key}",
        allowed_classifications=allowed_classifications,
        export_policy=export_policy,
    )


def _package_edge(
    edge: EngineeringKnowledgeGraphEdge,
    *,
    allowed_classifications: set[str],
    allowed_trust_levels: set[str],
    export_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    if edge.trust_level not in allowed_trust_levels:
        raise KnowledgePackageValidationError(f"Edge {edge.id} has non-exportable trust level")
    payload = serialize_graph_edge(edge)
    fact = _fact_payload(payload, fact_kind="edge")
    return _apply_export_control(
        fact,
        item_label=f"Edge {edge.id}",
        allowed_classifications=allowed_classifications,
        export_policy=export_policy,
    )


def _apply_export_control(
    fact: dict[str, Any],
    *,
    item_label: str,
    allowed_classifications: set[str],
    export_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    redacted, decision = apply_federation_export_control_to_fact(fact, export_policy=export_policy)
    if decision["action"] in {"blocked", "requires_review"}:
        reason = "; ".join(decision.get("reasons") or ["blocked by federation export policy"])
        raise KnowledgePackageValidationError(f"{item_label} cannot be exported: {reason}")
    if redacted.get("classification") not in allowed_classifications:
        raise KnowledgePackageValidationError(f"{item_label} has non-exportable classification")
    redacted["content_digest"] = _fact_content_digest(redacted)
    return redacted


def _fact_payload(payload: dict[str, Any], *, fact_kind: str) -> dict[str, Any]:
    safe = {
        "fact_kind": fact_kind,
        "id": payload["id"],
        "type": payload.get("node_type") or payload.get("edge_type"),
        "key": payload.get("node_key") or payload.get("id"),
        "display_name": payload.get("display_name") or "",
        "summary": payload.get("summary") or "",
        "status": payload.get("status"),
        "scope_type": payload.get("scope_type"),
        "scope_id": payload.get("scope_id"),
        "scope_key": payload.get("scope_key"),
        "trust_level": payload.get("trust_level"),
        "classification": payload.get("classification"),
        "valid_from": payload.get("valid_from"),
        "valid_until": payload.get("valid_until"),
        "properties": payload.get("properties") or {},
        "provenance": payload.get("provenance") or {},
        "source_evidence": _source_evidence(payload.get("source_refs") or []),
    }
    if fact_kind == "edge":
        safe["source_node_id"] = payload.get("source_node_id")
        safe["target_node_id"] = payload.get("target_node_id")
    else:
        safe["aliases"] = [
            {
                "alias_type": alias.get("alias_type"),
                "alias_value": alias.get("alias_value"),
                "normalized_alias": alias.get("normalized_alias"),
            }
            for alias in payload.get("aliases") or []
            if isinstance(alias, dict)
        ]
    _reject_unsafe_payload(safe, path=f"facts.{fact_kind}.{safe['key']}")
    safe["content_digest"] = _fact_content_digest(safe)
    return safe


def _source_evidence(source_refs: list[Any]) -> list[dict[str, Any]]:
    allowed_keys = {"source_type", "source_ref", "source_id", "title", "url", "checksum", "created_at", "updated_at"}
    evidence: list[dict[str, Any]] = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        evidence.append({key: value for key, value in ref.items() if key in allowed_keys and value is not None})
    return evidence


def _package_classification(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    values = {str(item.get("classification") or "internal") for item in [*nodes, *edges]}
    return "internal" if "internal" in values else "public"


def _package_trust_level(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    order = ["verified", "official", "gold"]
    values = {str(item.get("trust_level") or "gold") for item in [*nodes, *edges]}
    return next((trust for trust in order if trust in values), "gold")
