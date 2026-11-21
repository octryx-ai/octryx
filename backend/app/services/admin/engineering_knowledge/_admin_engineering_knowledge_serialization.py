"""Serialization helpers for Engineering Knowledge admin responses."""

from __future__ import annotations

from typing import Any

from ....models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def serialize_source(source: EngineeringKnowledgePackSource) -> dict[str, Any]:
    metadata = as_dict(source.source_metadata)
    return {
        "id": source.id,
        "pack_version_id": source.pack_version_id,
        "source_key": source.source_key,
        "title": source.title,
        "source_uri": source.source_uri,
        "source_type": source.source_type,
        "trust_tier": source.trust_tier,
        "version_label": source.version_label,
        "checksum": source.checksum,
        "fetch_status": source.fetch_status,
        "freshness_status": source.freshness_status,
        "raw_archive_path": source.raw_archive_path,
        "parsed_archive_path": source.parsed_archive_path,
        "evidence_archive_path": source.evidence_archive_path,
        "metadata": metadata,
        "source_audit": as_dict(metadata.get("source_audit")),
        "created_at": iso(source.created_at),
        "updated_at": iso(source.updated_at),
    }


def serialize_item(item: EngineeringKnowledgePackItem) -> dict[str, Any]:
    content = item.content or ""
    metadata = as_dict(item.item_metadata)
    evidence = _item_evidence(item, metadata)
    return {
        "id": item.id,
        "pack_version_id": item.pack_version_id,
        "source_id": item.source_id,
        "item_key": item.item_key,
        "title": item.title,
        "summary": item.summary or "",
        "content": content,
        "content_preview": content[:1000],
        "tags": as_list(item.tags),
        "triggers": as_list(item.triggers),
        "version_scope": as_dict(item.version_scope),
        "retrieval_priority": item.retrieval_priority,
        "retrieval_rank": int(item.retrieval_rank or 0),
        "metadata": metadata,
        "evidence": evidence,
        "evidence_status": "complete" if evidence else "missing",
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def serialize_assignment(assignment: EngineeringKnowledgePackAssignment) -> dict[str, Any]:
    return {
        "id": assignment.id,
        "pack_version_id": assignment.pack_version_id,
        "scope_type": assignment.scope_type,
        "scope_id": assignment.scope_id,
        "workspace_id": assignment.workspace_id,
        "repository_id": assignment.repository_id,
        "stack_key": assignment.stack_key,
        "assignment_status": assignment.assignment_status,
        "priority": int(assignment.priority or 0),
        "assignment_policy": as_dict(assignment.assignment_policy),
        "assigned_by_user_id": assignment.assigned_by_user_id,
        "assigned_at": iso(assignment.assigned_at),
        "created_at": iso(assignment.created_at),
        "updated_at": iso(assignment.updated_at),
    }


def serialize_version(version: EngineeringKnowledgePackVersion, *, include_details: bool) -> dict[str, Any]:
    sources = list(version.sources or [])
    items = list(version.items or [])
    assignments = list(version.assignments or [])
    item_evidence_count = sum(1 for item in items if _item_evidence(item, as_dict(item.item_metadata)))
    payload: dict[str, Any] = {
        "id": version.id,
        "pack_id": version.pack_id,
        "version": int(version.version or 0),
        "status": version.status,
        "source_versions": as_dict(version.source_versions),
        "target_versions": as_dict(version.target_versions),
        "compatibility_facts": as_dict(version.compatibility_facts),
        "manifest": as_dict(version.manifest),
        "archive_root": version.archive_root,
        "quality_status": version.quality_status,
        "quality_report": as_dict(version.quality_report),
        "notes": version.notes or "",
        "created_by_user_id": version.created_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "published_at": iso(version.published_at),
        "created_at": iso(version.created_at),
        "updated_at": iso(version.updated_at),
        "source_count": len(sources),
        "item_count": len(items),
        "item_evidence_count": item_evidence_count,
        "assignment_count": len(assignments),
        "active_assignment_count": sum(1 for item in assignments if item.assignment_status == "active"),
    }
    if include_details:
        payload["sources"] = [serialize_source(source) for source in sources]
        payload["items"] = [serialize_item(item) for item in items]
        payload["assignments"] = [serialize_assignment(item) for item in assignments]
    return payload


def _item_evidence(item: EngineeringKnowledgePackItem, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = metadata.get("evidence")
    if isinstance(explicit, list) and explicit:
        return [entry for entry in explicit if isinstance(entry, dict)]
    source_uri = str(metadata.get("source_uri") or "").strip()
    trust_tier = str(metadata.get("trust_tier") or "").strip()
    if item.source:
        return [
            {
                "source_id": item.source.id,
                "source_key": item.source.source_key,
                "title": item.source.title,
                "source_uri": item.source.source_uri,
                "source_type": item.source.source_type,
                "trust_tier": item.source.trust_tier,
                "checksum": item.source.checksum,
                "raw_archive_path": item.source.raw_archive_path,
                "parsed_archive_path": item.source.parsed_archive_path,
                "evidence_archive_path": item.source.evidence_archive_path,
                "freshness_status": item.source.freshness_status,
                "fetch_status": item.source.fetch_status,
            }
        ]
    if source_uri:
        return [
            {
                "source_uri": source_uri,
                "trust_tier": trust_tier or "unknown",
                "source_type": "external",
            }
        ]
    return []


def serialize_pack(pack: EngineeringKnowledgePack, *, include_details: bool) -> dict[str, Any]:
    versions = sorted(pack.versions or [], key=lambda item: int(item.version or 0), reverse=True)
    published = [item for item in versions if item.status == "published"]
    return {
        "id": pack.id,
        "key": pack.key,
        "name": pack.name,
        "description": pack.description or "",
        "stack_key": pack.stack_key,
        "lifecycle_status": pack.lifecycle_status,
        "is_active": bool(pack.is_active),
        "source_policy": as_dict(pack.source_policy),
        "freshness_policy": as_dict(pack.freshness_policy),
        "retrieval_policy": as_dict(pack.retrieval_policy),
        "toolchain_policy": as_dict(pack.toolchain_policy),
        "resolution_policy": as_dict(pack.resolution_policy),
        "created_by_user_id": pack.created_by_user_id,
        "created_at": iso(pack.created_at),
        "updated_at": iso(pack.updated_at),
        "latest_published_version_id": published[0].id if published else None,
        "versions": [serialize_version(version, include_details=include_details) for version in versions],
    }


def serialize_build_run(run: EngineeringKnowledgePackBuildRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "pack_id": run.pack_id,
        "pack_version_id": run.pack_version_id,
        "pack_key": run.pack.key if run.pack else None,
        "pack_version": int(run.pack_version.version or 0) if run.pack_version else None,
        "trigger": run.trigger,
        "prompt": run.prompt or "",
        "stack_key": run.stack_key,
        "source_versions": as_dict(run.source_versions),
        "target_versions": as_dict(run.target_versions),
        "status": run.status,
        "source_plan": as_dict(run.source_plan),
        "acquisition_policy": as_dict(run.acquisition_policy),
        "quality_report": as_dict(run.quality_report),
        "publish_decision": run.publish_decision,
        "approval_status": run.approval_status,
        "blocker_details": as_list(run.blocker_details),
        "created_by_user_id": run.created_by_user_id,
        "started_at": iso(run.started_at),
        "completed_at": iso(run.completed_at),
        "created_at": iso(run.created_at),
        "updated_at": iso(run.updated_at),
    }
