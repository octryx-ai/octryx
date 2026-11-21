"""API views of flow definitions and their versions."""

from __future__ import annotations

from typing import Any

from ...models import FlowDefinition, FlowDefinitionVersion


def serialize_flow(row: FlowDefinition, *, include_versions: bool = False) -> dict[str, Any]:
    versions = sorted(row.versions, key=lambda item: item.version)
    payload: dict[str, Any] = {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "description": row.description or "",
        "project_id": row.project_id,
        "status": row.status,
        "is_active": bool(row.is_active),
        "current_version_id": row.current_version_id,
        "latest_version": versions[-1].version if versions else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_versions:
        payload["versions"] = [serialize_flow_version(version) for version in versions]
    return payload


def serialize_flow_version(row: FlowDefinitionVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "flow_id": row.flow_id,
        "version": row.version,
        "status": row.status,
        "definition": dict(row.definition_json or {}),
        "validation_report": dict(row.validation_report or {}),
        "publish_metadata": dict(row.publish_metadata or {}),
        "runtime_settings": dict(row.runtime_settings or {}),
        "policy_bindings": dict(row.policy_bindings or {}),
        "created_by": row.created_by,
        "published_by": row.published_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }
