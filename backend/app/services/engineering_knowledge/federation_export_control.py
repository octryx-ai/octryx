"""Export-control policy and redaction for Engineering Knowledge federation."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import EngineeringKnowledgeGraphNode
from .federation_export_decision import (
    _decision_action,
    _decision_reasons,
    _export_classification,
    _redact_fact,
    _secret_value_paths,
    _unsafe_paths,
)
from .federation_export_labels import _fact_labels, build_federation_export_policy
from .graph_store_serializers import serialize_graph_node


def apply_federation_export_control_to_fact(
    fact: dict[str, Any],
    *,
    export_policy: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a redacted export fact plus an auditable export decision."""

    policy = build_federation_export_policy(export_policy)
    working = copy.deepcopy(fact)
    labels = _fact_labels(working, policy=policy)
    unsafe_paths = _unsafe_paths(working)
    secret_paths = _secret_value_paths(working)
    redacted, redaction = _redact_fact(working, policy=policy)
    labels.update(redaction["labels"])
    reasons = _decision_reasons(labels=labels, unsafe_paths=unsafe_paths, secret_paths=secret_paths, policy=policy)
    action = _decision_action(labels=labels, unsafe_paths=unsafe_paths, secret_paths=secret_paths, policy=policy)
    if action in {"exportable", "redacted"}:
        redacted["classification"] = _export_classification(labels)
        redacted["export_control"] = {
            "action": action,
            "labels": sorted(labels),
            "reasons": reasons,
            "redacted_paths": redaction["paths"],
            "redaction_types": redaction["types"],
        }
    decision = {
        "fact_id": str(fact.get("id") or ""),
        "fact_key": str(fact.get("key") or ""),
        "fact_type": str(fact.get("type") or ""),
        "action": action,
        "labels": sorted(labels),
        "reasons": reasons,
        "redacted_paths": redaction["paths"],
        "redaction_types": redaction["types"],
        "original_classification": str(fact.get("classification") or ""),
        "export_classification": redacted.get("classification") if action in {"exportable", "redacted"} else None,
    }
    return redacted, decision


async def preview_federation_export_control(
    db: AsyncSession,
    *,
    node_ids: list[str],
    export_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview export-control decisions for graph facts without creating a package."""

    safe_ids = [str(item).strip() for item in node_ids if str(item or "").strip()]
    nodes = []
    if safe_ids:
        nodes = (
            (
                await db.execute(
                    select(EngineeringKnowledgeGraphNode)
                    .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
                    .where(EngineeringKnowledgeGraphNode.id.in_(safe_ids))
                    .order_by(EngineeringKnowledgeGraphNode.updated_at.desc())
                )
            )
            .scalars()
            .unique()
            .all()
        )
    decisions: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    for node in nodes:
        fact = _preview_node_fact(serialize_graph_node(node))
        redacted, decision = apply_federation_export_control_to_fact(fact, export_policy=export_policy)
        decisions.append(decision)
        previews.append(_safe_preview_fact(redacted))
    counts = {
        "exportable": len([item for item in decisions if item["action"] == "exportable"]),
        "redacted": len([item for item in decisions if item["action"] == "redacted"]),
        "requires_review": len([item for item in decisions if item["action"] == "requires_review"]),
        "blocked": len([item for item in decisions if item["action"] == "blocked"]),
    }
    return {
        "node_count": len(nodes),
        "missing_node_ids": sorted(set(safe_ids) - {node.id for node in nodes}),
        "counts": counts,
        "decisions": decisions,
        "preview": previews,
    }


def _preview_node_fact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_kind": "node",
        "id": payload["id"],
        "type": payload.get("node_type"),
        "key": payload.get("node_key"),
        "display_name": payload.get("display_name") or "",
        "summary": payload.get("summary") or "",
        "status": payload.get("status"),
        "scope_type": payload.get("scope_type"),
        "scope_id": payload.get("scope_id"),
        "scope_key": payload.get("scope_key"),
        "trust_level": payload.get("trust_level"),
        "classification": payload.get("classification"),
        "properties": payload.get("properties") or {},
        "provenance": payload.get("provenance") or {},
        "source_evidence": payload.get("source_refs") or [],
        "aliases": payload.get("aliases") or [],
    }



def _safe_preview_fact(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": fact.get("id"),
        "key": fact.get("key"),
        "type": fact.get("type"),
        "display_name": fact.get("display_name"),
        "summary": fact.get("summary"),
        "classification": fact.get("classification"),
        "export_control": fact.get("export_control"),
    }


def _string_values(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_string_values(item) for item in value.values()).lower()
    if isinstance(value, list):
        return " ".join(_string_values(item) for item in value).lower()
    return str(value or "").lower()


def _term_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip().lower() for item in value]
    else:
        items = []
    return [item for item in items if item]


__all__ = [
    "apply_federation_export_control_to_fact",
    "preview_federation_export_control",
]
