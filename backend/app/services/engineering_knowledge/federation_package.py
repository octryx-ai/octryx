"""Signed Engineering Knowledge Package format.

This module deliberately does not persist publisher keys. A later federation UI/API
slice should resolve signing and verification keys through the secret subsystem.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import EngineeringKnowledgeGraphEdge, EngineeringKnowledgeGraphNode
from ...time_utils import utc_now
from .federation_package_common import (
    DEFAULT_EXPORT_CLASSIFICATIONS,
    DEFAULT_EXPORT_TRUST_LEVELS,
    PACKAGE_SCHEMA_VERSION,
    PACKAGE_SIGNATURE_ALGORITHM,
    KnowledgePackageValidationError,
    _fact_content_digest,
    _reject_unsafe_payload,
    _require_signing_key,
    _signature_value,
    _without_signature,
)
from .federation_package_facts import _apply_export_control, _fact_payload, _unsigned_package
from .graph_store_serializers import serialize_graph_node


async def create_signed_engineering_knowledge_package(
    db: AsyncSession,
    *,
    node_ids: list[str],
    publisher_instance_id: str,
    signing_key: str,
    signing_key_id: str = "local-dev",
    package_id: str | None = None,
    usage_policy: dict[str, Any] | None = None,
    compatibility: dict[str, Any] | None = None,
    redaction: dict[str, Any] | None = None,
    retractions: list[dict[str, Any]] | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    allowed_classifications: set[str] | None = None,
    allowed_trust_levels: set[str] | None = None,
    export_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and sign a portable package from reviewed graph facts."""

    if not node_ids:
        raise KnowledgePackageValidationError("At least one graph node is required")
    nodes = await _load_export_nodes(db, node_ids)
    allowed_classifications = allowed_classifications or DEFAULT_EXPORT_CLASSIFICATIONS
    allowed_trust_levels = allowed_trust_levels or DEFAULT_EXPORT_TRUST_LEVELS
    edges = await _load_export_edges(db, {node.id for node in nodes})
    package = _unsigned_package(
        nodes=nodes,
        edges=edges,
        publisher_instance_id=publisher_instance_id,
        package_id=package_id,
        usage_policy=usage_policy,
        compatibility=compatibility,
        redaction=redaction,
        retractions=retractions,
        valid_from=valid_from,
        valid_until=valid_until,
        allowed_classifications=allowed_classifications,
        allowed_trust_levels=allowed_trust_levels,
        export_policy=export_policy,
    )
    validate_engineering_knowledge_package_payload(package)
    return sign_engineering_knowledge_package(package, signing_key=signing_key, signing_key_id=signing_key_id)


async def _load_export_nodes(db: AsyncSession, node_ids: list[str]) -> list[EngineeringKnowledgeGraphNode]:
    nodes = (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
                .where(EngineeringKnowledgeGraphNode.id.in_(node_ids))
                .order_by(EngineeringKnowledgeGraphNode.scope_key.asc(), EngineeringKnowledgeGraphNode.node_key.asc())
            )
        )
        .scalars()
        .all()
    )
    found_ids = {node.id for node in nodes}
    missing = sorted(set(node_ids) - found_ids)
    if missing:
        raise KnowledgePackageValidationError(f"Unknown graph node id(s): {', '.join(missing)}")
    return nodes


async def _load_export_edges(db: AsyncSession, node_id_set: set[str]) -> list[EngineeringKnowledgeGraphEdge]:
    return (
        (
            await db.execute(
                select(EngineeringKnowledgeGraphEdge)
                .where(
                    EngineeringKnowledgeGraphEdge.status == "active",
                    EngineeringKnowledgeGraphEdge.source_node_id.in_(node_id_set),
                    EngineeringKnowledgeGraphEdge.target_node_id.in_(node_id_set),
                )
                .order_by(EngineeringKnowledgeGraphEdge.edge_type.asc())
            )
        )
        .scalars()
        .all()
    )


def sign_engineering_knowledge_package(
    package: dict[str, Any],
    *,
    signing_key: str,
    signing_key_id: str = "local-dev",
) -> dict[str, Any]:
    """Attach a deterministic HMAC signature to a package payload."""

    _require_signing_key(signing_key)
    unsigned = _without_signature(package)
    signature_value = _signature_value(unsigned, signing_key=signing_key)
    signed = dict(unsigned)
    signed["signature"] = {
        "algorithm": PACKAGE_SIGNATURE_ALGORITHM,
        "key_id": str(signing_key_id or "local-dev"),
        "signed_at": utc_now().isoformat(),
        "value": signature_value,
    }
    return signed


def verify_engineering_knowledge_package_signature(
    package: dict[str, Any],
    *,
    signing_key: str,
) -> dict[str, Any]:
    """Verify the package signature and return a structured result."""

    _require_signing_key(signing_key)
    signature = dict(package.get("signature") or {})
    supplied = str(signature.get("value") or "")
    algorithm = str(signature.get("algorithm") or "")
    if algorithm != PACKAGE_SIGNATURE_ALGORITHM:
        return {"valid": False, "reason": "unsupported_signature_algorithm", "algorithm": algorithm}
    expected = _signature_value(_without_signature(package), signing_key=signing_key)
    valid = hmac.compare_digest(supplied, expected)
    return {
        "valid": valid,
        "reason": "ok" if valid else "invalid_signature",
        "algorithm": PACKAGE_SIGNATURE_ALGORITHM,
        "key_id": signature.get("key_id"),
        "package_id": package.get("package_id"),
    }


async def dry_run_import_engineering_knowledge_package(
    db: AsyncSession,
    package: dict[str, Any],
    *,
    verification_key: str | None = None,
) -> dict[str, Any]:
    """Validate package import compatibility and conflicts without mutating graph state."""

    errors = validate_engineering_knowledge_package_payload(package, raise_on_error=False)
    signature_result: dict[str, Any] | None = None
    if verification_key is not None:
        signature_result = verify_engineering_knowledge_package_signature(package, signing_key=verification_key)
        if not signature_result["valid"]:
            errors.append({"code": "invalid_signature", "message": signature_result["reason"]})
    facts = dict(package.get("facts") or {})
    nodes = [dict(node) for node in facts.get("nodes") or [] if isinstance(node, dict)]
    conflicts = await _detect_import_conflicts(db, nodes)
    return {
        "status": "blocked" if errors else "ready",
        "dry_run": True,
        "package_id": package.get("package_id"),
        "schema_version": package.get("schema_version"),
        "signature": signature_result,
        "node_count": len(nodes),
        "edge_count": len([edge for edge in facts.get("edges") or [] if isinstance(edge, dict)]),
        "errors": errors,
        "conflicts": conflicts,
        "importable_node_count": max(0, len(nodes) - len(conflicts)) if not errors else 0,
        "mutated": False,
    }


def validate_engineering_knowledge_package_payload(
    package: dict[str, Any],
    *,
    raise_on_error: bool = True,
) -> list[dict[str, str]]:
    """Validate package schema and export safety."""

    errors: list[dict[str, str]] = []
    if package.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        errors.append(
            {
                "code": "unsupported_schema_version",
                "message": f"Unsupported schema_version: {package.get('schema_version')}",
            }
        )
    for key in ("package_id", "publisher", "created_at", "classification", "trust_level", "facts"):
        if not package.get(key):
            errors.append({"code": "missing_required_field", "message": f"{key} is required"})
    publisher = dict(package.get("publisher") or {})
    if not publisher.get("instance_id"):
        errors.append({"code": "missing_publisher_instance", "message": "publisher.instance_id is required"})
    classification = str(package.get("classification") or "").lower()
    if classification not in DEFAULT_EXPORT_CLASSIFICATIONS:
        errors.append({"code": "blocked_classification", "message": f"{classification} cannot be exported"})
    try:
        _reject_unsafe_payload(package, path="package")
    except KnowledgePackageValidationError as exc:
        errors.append({"code": "unsafe_payload", "message": str(exc)})
    facts = dict(package.get("facts") or {})
    if not facts.get("nodes"):
        errors.append({"code": "empty_package", "message": "At least one node fact is required"})
    for node in [dict(item) for item in facts.get("nodes") or [] if isinstance(item, dict)]:
        _validate_fact_node(node, errors)
    if errors and raise_on_error:
        raise KnowledgePackageValidationError("; ".join(error["message"] for error in errors))
    return errors


async def _detect_import_conflicts(db: AsyncSession, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for node in nodes:
        existing = (
            await db.execute(
                select(EngineeringKnowledgeGraphNode)
                .options(selectinload(EngineeringKnowledgeGraphNode.aliases))
                .where(
                    EngineeringKnowledgeGraphNode.scope_key == node.get("scope_key"),
                    EngineeringKnowledgeGraphNode.node_type == node.get("type"),
                    EngineeringKnowledgeGraphNode.node_key == node.get("key"),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            continue
        existing_fact = _fact_payload(serialize_graph_node(existing), fact_kind="node")
        existing_digest = _apply_export_control(
            existing_fact,
            item_label=f"Node {existing.node_key}",
            allowed_classifications=DEFAULT_EXPORT_CLASSIFICATIONS,
            export_policy=None,
        )["content_digest"]
        conflicts.append(
            {
                "node_id": existing.id,
                "node_key": existing.node_key,
                "scope_key": existing.scope_key,
                "conflict": "content_differs" if existing_digest != node.get("content_digest") else "duplicate",
            }
        )
    return conflicts


def _validate_fact_node(node: dict[str, Any], errors: list[dict[str, str]]) -> None:
    if node.get("fact_kind") != "node":
        errors.append({"code": "invalid_fact_kind", "message": "Node facts must use fact_kind=node"})
    if node.get("status") != "active":
        errors.append({"code": "inactive_fact", "message": f"{node.get('key')} is not active"})
    if node.get("classification") not in DEFAULT_EXPORT_CLASSIFICATIONS:
        errors.append({"code": "blocked_fact_classification", "message": f"{node.get('key')} classification blocked"})
    if node.get("trust_level") not in DEFAULT_EXPORT_TRUST_LEVELS:
        errors.append({"code": "blocked_fact_trust", "message": f"{node.get('key')} trust level blocked"})
    expected_digest = _fact_content_digest(node)
    if node.get("content_digest") != expected_digest:
        errors.append({"code": "invalid_fact_digest", "message": f"{node.get('key')} digest mismatch"})
