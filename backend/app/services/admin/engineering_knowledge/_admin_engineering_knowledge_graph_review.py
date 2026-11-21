"""Review actions and list filters for Engineering Knowledge graph nodes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_

from ....models import EngineeringKnowledgeGraphNode
from ....time_utils import utc_now
from ...engineering_knowledge import mark_engineering_knowledge_review_lifecycle
from ._admin_engineering_knowledge_common import (
    _GRAPH_CLASSIFICATIONS,
    _GRAPH_NODE_STATUSES,
    _GRAPH_TRUST_LEVELS,
    _optional_id,
)


def _graph_node_filters(
    *,
    query: str,
    node_type: str,
    status: str,
    trust_level: str,
    classification: str,
    scope_type: str,
    scope_id: str,
    repository_id: str,
    source: str,
    reviewer: str,
    validity: str,
) -> list[Any]:
    filters: list[Any] = []
    if node_type:
        filters.append(EngineeringKnowledgeGraphNode.node_type == _safe_graph_text(node_type))
    if status:
        filters.append(EngineeringKnowledgeGraphNode.status == _safe_graph_choice(status, _GRAPH_NODE_STATUSES))
    if trust_level:
        filters.append(
            EngineeringKnowledgeGraphNode.trust_level == _safe_graph_choice(trust_level, _GRAPH_TRUST_LEVELS)
        )
    if classification:
        filters.append(
            EngineeringKnowledgeGraphNode.classification == _safe_graph_choice(classification, _GRAPH_CLASSIFICATIONS)
        )
    if scope_type:
        filters.append(EngineeringKnowledgeGraphNode.scope_type == _safe_graph_text(scope_type))
    if scope_id:
        filters.append(EngineeringKnowledgeGraphNode.scope_id == scope_id.strip())
    if repository_id:
        filters.append(EngineeringKnowledgeGraphNode.repository_id == repository_id.strip())
    if query:
        needle = f"%{query.strip().lower()}%"
        filters.append(
            or_(
                func.lower(EngineeringKnowledgeGraphNode.node_key).like(needle),
                func.lower(EngineeringKnowledgeGraphNode.display_name).like(needle),
                func.lower(EngineeringKnowledgeGraphNode.summary).like(needle),
                func.lower(cast(EngineeringKnowledgeGraphNode.properties_json, String)).like(needle),
            )
        )
    if source:
        filters.append(
            func.lower(cast(EngineeringKnowledgeGraphNode.source_refs_json, String)).like(f"%{source.lower()}%")
        )
    if reviewer:
        filters.append(
            func.lower(cast(EngineeringKnowledgeGraphNode.properties_json, String)).like(f"%{reviewer.lower()}%")
        )
    filters.extend(_validity_filters(validity))
    return filters


def _validity_filters(validity: str) -> list[Any]:
    now = utc_now()
    if validity == "expired":
        return [
            EngineeringKnowledgeGraphNode.valid_until.is_not(None),
            EngineeringKnowledgeGraphNode.valid_until <= now,
        ]
    if validity == "valid":
        return [
            or_(
                EngineeringKnowledgeGraphNode.valid_until.is_(None),
                EngineeringKnowledgeGraphNode.valid_until > now,
            )
        ]
    return []


def _apply_graph_review_action(
    node: EngineeringKnowledgeGraphNode,
    *,
    action: str,
    payload: dict[str, Any],
    admin_id: str,
) -> None:
    properties = dict(node.properties_json or {})
    reason = str(payload.get("reason") or "").strip()
    if action in _LIFECYCLE_ACTIONS:
        _apply_lifecycle_action(node, action=action, payload=payload, reason=reason, admin_id=admin_id)
    elif action in _MARKING_ACTIONS:
        _apply_marking_action(
            node, action=action, payload=payload, reason=reason, admin_id=admin_id, properties=properties
        )
    if action == "edit_metadata":
        _apply_graph_metadata_edits(node, payload)
        mark_engineering_knowledge_review_lifecycle(
            node,
            status=node.status,
            reason=reason or "Metadata edited by Engineering Knowledge review.",
            actor_id=admin_id,
        )
    else:
        metadata_payload = {key: value for key, value in payload.items() if key in {"classification"}}
        _apply_graph_metadata_edits(node, metadata_payload)
    current_properties = dict(node.properties_json or {})
    review_history = _list(current_properties.get("review_history") or properties.get("review_history"))
    node.properties_json = {
        **properties,
        **current_properties,
        "review_history": [
            *review_history[:24],
            {
                "action": action,
                "reason": reason,
                "reviewed_by_user_id": admin_id,
                "reviewed_at": utc_now().isoformat(),
            },
        ],
    }


_LIFECYCLE_ACTIONS = {"promote", "reject", "retract", "expire"}
_MARKING_ACTIONS = {"mark_non_shareable", "publish_candidate", "merge"}


def _apply_lifecycle_action(
    node: EngineeringKnowledgeGraphNode, *, action: str, payload: dict[str, Any], reason: str, admin_id: str
) -> None:
    if action == "promote":
        node.status = _safe_graph_choice(payload.get("status") or "active", _GRAPH_NODE_STATUSES)
        node.trust_level = _safe_graph_choice(payload.get("trust_level") or "gold", _GRAPH_TRUST_LEVELS)
        mark_engineering_knowledge_review_lifecycle(
            node,
            status=node.status,
            reason=reason or "Promoted by Engineering Knowledge review.",
            actor_id=admin_id,
        )
    elif action == "reject":
        node.status = "rejected"
        node.trust_level = "untrusted"
        mark_engineering_knowledge_review_lifecycle(
            node,
            status="rejected",
            reason=reason or "Rejected by Engineering Knowledge review.",
            actor_id=admin_id,
        )
    elif action == "retract":
        node.status = "retracted"
        mark_engineering_knowledge_review_lifecycle(
            node,
            status="retracted",
            reason=reason or "Retracted by Engineering Knowledge review.",
            actor_id=admin_id,
        )
    elif action == "expire":
        node.status = "expired"
        node.valid_until = utc_now()
        mark_engineering_knowledge_review_lifecycle(
            node,
            status="expired",
            reason=reason or "Expired by Engineering Knowledge review.",
            actor_id=admin_id,
        )


def _apply_marking_action(
    node: EngineeringKnowledgeGraphNode,
    *,
    action: str,
    payload: dict[str, Any],
    reason: str,
    admin_id: str,
    properties: dict[str, Any],
) -> None:
    if action == "mark_non_shareable":
        node.classification = "restricted"
        properties["shareability"] = "non_shareable"
        mark_engineering_knowledge_review_lifecycle(
            node,
            status=node.status,
            reason=reason or "Marked non-shareable by Engineering Knowledge review.",
            actor_id=admin_id,
            extra={"classification": "restricted", "shareability": "non_shareable"},
        )
    elif action == "publish_candidate":
        properties["federation_publish_candidate"] = True
        mark_engineering_knowledge_review_lifecycle(
            node,
            status=node.status,
            reason=reason or "Marked as publish candidate by Engineering Knowledge review.",
            actor_id=admin_id,
            extra={"federation_publish_candidate": True},
        )
    elif action == "merge":
        target_node_id = _optional_id(payload.get("target_node_id"))
        if not target_node_id:
            raise HTTPException(status_code=422, detail="target_node_id is required for merge")
        properties["merged_into_node_id"] = target_node_id
        mark_engineering_knowledge_review_lifecycle(
            node,
            status="retracted",
            reason=reason or "Merged into another Engineering Knowledge fact.",
            actor_id=admin_id,
            extra={"merged_into_node_id": target_node_id},
        )


def _apply_graph_metadata_edits(node: EngineeringKnowledgeGraphNode, payload: dict[str, Any]) -> None:
    if payload.get("display_name") is not None:
        node.display_name = str(payload.get("display_name") or "").strip()[:500]
    if payload.get("summary") is not None:
        node.summary = str(payload.get("summary") or "").strip()[:4000]
    if payload.get("status"):
        node.status = _safe_graph_choice(payload.get("status"), _GRAPH_NODE_STATUSES)
    if payload.get("trust_level"):
        node.trust_level = _safe_graph_choice(payload.get("trust_level"), _GRAPH_TRUST_LEVELS)
    if payload.get("classification"):
        node.classification = _safe_graph_choice(payload.get("classification"), _GRAPH_CLASSIFICATIONS)


def _safe_graph_choice(value: Any, allowed: set[str]) -> str:
    text = _safe_graph_text(value)
    if text not in allowed:
        raise HTTPException(status_code=422, detail=f"Unsupported Engineering Knowledge value: {text}")
    return text


def _safe_graph_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
