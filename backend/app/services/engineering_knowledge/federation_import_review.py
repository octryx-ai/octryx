"""Review and conflict handling for imported Engineering Knowledge packages."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AuditLog,
    EngineeringKnowledgeFederationPackage,
    EngineeringKnowledgeGraphNode,
    User,
)
from ...time_utils import utc_now
from ..access_control import require_existing_workspace
from .federation_import_conflicts import _package_node_facts, _parse_datetime
from .federation_serializers import serialize_federation_package
from .graph_store_serializers import serialize_graph_node
from .graph_store_writes import upsert_engineering_knowledge_node

IMPORT_REVIEW_ACTIONS = {
    "accept",
    "accept_lower_trust",
    "reject",
    "quarantine",
    "map_local_entity",
    "merge_duplicate",
    "local_override",
}
# A scope of these types names a Workspace in ``scope_id``.
WORKSPACE_SCOPE_TYPES = {"workspace", "project"}
TRUST_LEVELS = {"bronze", "silver", "gold", "official", "verified", "untrusted"}


async def review_imported_engineering_knowledge_package(
    db: AsyncSession,
    *,
    package_record_id: str,
    action: str,
    payload: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    """Apply a human import-review action without silently overwriting local facts. A Workspace the review scopes the
    imported facts to is resolved first: an unknown one is 404 ``project_not_found`` before anything is written."""

    scope = _review_scope(payload)
    await require_existing_workspace(db, scope["workspace_id"])
    if scope["scope_type"] in WORKSPACE_SCOPE_TYPES:
        await require_existing_workspace(db, scope["scope_id"])
    safe_action = str(action or "").strip().lower()
    if safe_action not in IMPORT_REVIEW_ACTIONS:
        raise HTTPException(status_code=400, detail="Unsupported federation import review action")
    record = await _get_import_record(db, package_record_id)
    imported_nodes: list[dict[str, Any]] = []
    review_metadata = _review_metadata(record, action=safe_action, payload=payload, current_user=current_user)

    if safe_action in {"accept", "accept_lower_trust", "map_local_entity"}:
        local_trust = _local_trust_level(record, action=safe_action, payload=payload)
        imported_nodes = await _accept_imported_facts(
            db,
            record=record,
            local_trust=local_trust,
            payload=payload,
            current_user=current_user,
            mapped_local_entity_id=_optional_text(payload.get("target_node_id")),
        )
        record.status = "accepted"
        record.review_status = "accepted_lower_trust" if safe_action == "accept_lower_trust" else safe_action
    elif safe_action == "reject":
        record.status = "rejected"
        record.review_status = "rejected"
    elif safe_action == "quarantine":
        record.status = "quarantined"
        record.review_status = "quarantined"
    elif safe_action == "merge_duplicate":
        record.status = "accepted"
        record.review_status = "merged_duplicate"
    elif safe_action == "local_override":
        record.status = "accepted"
        record.review_status = "local_override"

    record.content_json = {**dict(record.content_json or {}), "import_review": review_metadata}
    db.add(_import_review_audit(current_user.id, record=record, action=safe_action, details=review_metadata))
    await db.flush()
    return {
        "action": safe_action,
        "package": serialize_federation_package(record),
        "imported_nodes": imported_nodes,
        "review": review_metadata,
    }


async def _accept_imported_facts(
    db: AsyncSession,
    *,
    record: EngineeringKnowledgeFederationPackage,
    local_trust: str,
    payload: dict[str, Any],
    current_user: User,
    mapped_local_entity_id: str | None,
) -> list[dict[str, Any]]:
    package = dict(record.content_json or {})
    scope = _review_scope(payload)
    imported: list[dict[str, Any]] = []
    for fact in _package_node_facts(package):
        node = await upsert_engineering_knowledge_node(
            db,
            node_type=str(fact.get("type") or "evidence_source"),
            node_key=_namespaced_node_key(record.publisher_instance_id, str(fact.get("key") or fact.get("id") or "")),
            display_name=str(fact.get("display_name") or fact.get("key") or "Imported knowledge"),
            summary=str(fact.get("summary") or ""),
            status="active",
            scope_type=scope["scope_type"],
            scope_id=scope["scope_id"],
            workspace_id=scope["workspace_id"],
            repository_id=scope["repository_id"],
            trust_level=local_trust,
            classification=_safe_classification(fact.get("classification")),
            valid_from=_parse_datetime(fact.get("valid_from")),
            valid_until=_parse_datetime(fact.get("valid_until")),
            properties={
                **dict(fact.get("properties") or {}),
                "federation": _federation_metadata(
                    record,
                    fact=fact,
                    local_trust=local_trust,
                    status="accepted",
                    mapped_local_entity_id=mapped_local_entity_id,
                    scope=scope,
                ),
            },
            provenance=_imported_provenance(record),
            source_refs=_imported_source_refs(record, fact),
            aliases=_imported_aliases(record, fact),
            created_by_user_id=current_user.id,
        )
        imported.append(serialize_graph_node(await _load_node_with_aliases(db, node.id)))
    return imported


def _imported_provenance(record: EngineeringKnowledgeFederationPackage) -> dict[str, Any]:
    return {
        "source": "federated_engineering_knowledge_package",
        "publisher_instance_id": record.publisher_instance_id,
        "package_id": record.package_id,
        "package_record_id": record.id,
    }


def _imported_source_refs(record: EngineeringKnowledgeFederationPackage, fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "federation_package",
            "source_ref": record.package_id,
            "title": f"Federated package {record.package_id}",
            "checksum": record.package_checksum,
        },
        *list(fact.get("source_evidence") or [])[:5],
    ]


def _imported_aliases(record: EngineeringKnowledgeFederationPackage, fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "alias_type": "federated_source_key",
            "alias_value": str(fact.get("key") or ""),
            "source_refs": [{"source_type": "federation_package", "source_ref": record.package_id}],
        }
    ]


async def _load_node_with_aliases(db: AsyncSession, node_id: str) -> EngineeringKnowledgeGraphNode:
    return (
        await db.execute(
            select(EngineeringKnowledgeGraphNode)
            .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
            .where(EngineeringKnowledgeGraphNode.id == node_id)
        )
    ).scalar_one()


async def _get_import_record(db: AsyncSession, package_record_id: str) -> EngineeringKnowledgeFederationPackage:
    record = (
        await db.execute(
            select(EngineeringKnowledgeFederationPackage)
            .options(selectinload(EngineeringKnowledgeFederationPackage.feed))
            .where(EngineeringKnowledgeFederationPackage.id == package_record_id)
        )
    ).scalar_one_or_none()
    if record is None or record.direction != "imported":
        raise HTTPException(status_code=404, detail="Imported federation package not found")
    return record


def _review_metadata(
    record: EngineeringKnowledgeFederationPackage,
    *,
    action: str,
    payload: dict[str, Any],
    current_user: User,
) -> dict[str, Any]:
    return {
        "action": action,
        "reviewed_by_user_id": current_user.id,
        "reviewed_at": utc_now().isoformat(),
        "reason": str(payload.get("reason") or "").strip(),
        "local_trust_level": _local_trust_level(record, action=action, payload=payload),
        "applicability_scope": _review_scope(payload),
        "target_node_id": _optional_text(payload.get("target_node_id")),
    }


def _federation_metadata(
    record: EngineeringKnowledgeFederationPackage,
    *,
    fact: dict[str, Any],
    local_trust: str,
    status: str,
    mapped_local_entity_id: str | None,
    scope: dict[str, Any],
) -> dict[str, Any]:
    signature = dict(record.signature or {})
    return {
        "origin": "imported",
        "publisher_instance_id": record.publisher_instance_id,
        "package_id": record.package_id,
        "package_record_id": record.id,
        "package_checksum": record.package_checksum,
        "signature_key_id": signature.get("key_id"),
        "original_trust_level": str(fact.get("trust_level") or record.trust_level),
        "local_trust_level": local_trust,
        "import_status": status,
        "mapped_local_entity_id": mapped_local_entity_id,
        "applicability_scope": scope,
    }


def _review_scope(payload: dict[str, Any]) -> dict[str, Any]:
    scope = dict(payload.get("applicability_scope") or {})
    scope_type = str(scope.get("scope_type") or payload.get("scope_type") or "global").strip().lower()
    if scope_type not in {"global", "workspace", "project", "repository"}:
        scope_type = "global"
    return {
        "scope_type": scope_type,
        "scope_id": _optional_text(scope.get("scope_id") or payload.get("scope_id")),
        "workspace_id": _optional_text(scope.get("workspace_id") or payload.get("workspace_id")),
        "repository_id": _optional_text(scope.get("repository_id") or payload.get("repository_id")),
    }


def _local_trust_level(record: EngineeringKnowledgeFederationPackage, *, action: str, payload: dict[str, Any]) -> str:
    if action == "accept_lower_trust":
        default = "silver" if record.trust_level in {"gold", "official", "verified"} else "bronze"
    else:
        default = record.trust_level if record.trust_level in TRUST_LEVELS else "silver"
    requested = str(payload.get("local_trust_level") or default).strip().lower()
    return requested if requested in TRUST_LEVELS else default


def _namespaced_node_key(publisher: str, key: str) -> str:
    safe_publisher = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in publisher)[:80]
    safe_key = key.strip() or "unknown"
    return f"federated:{safe_publisher}:{safe_key}"[:300]


def _safe_classification(value: Any) -> str:
    text = str(value or "internal").strip().lower()
    return text if text in {"public", "internal"} else "internal"


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _import_review_audit(
    user_id: str,
    *,
    record: EngineeringKnowledgeFederationPackage,
    action: str,
    details: dict[str, Any],
) -> AuditLog:
    return AuditLog(
        user_id=user_id,
        action=f"engineering_knowledge_federation.import_{action}",
        resource_type="engineering_knowledge_federation_package",
        resource_id=record.id,
        details=details,
    )


__all__ = ["review_imported_engineering_knowledge_package"]
