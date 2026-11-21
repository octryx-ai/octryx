"""Serialization helpers for design artifacts and trace links."""

from __future__ import annotations

from app.services.design_artifact.common import normalize_id_list, normalize_metadata

from ...models import DesignArtifact, DesignArtifactTraceLink


def serialize_design_artifact(
    artifact: DesignArtifact,
    *,
    owner_labels: dict[str, str] | None = None,
) -> dict[str, object]:
    metadata = normalize_metadata(artifact.metadata_json)
    linked_repository_ids = normalize_id_list(metadata.get("linked_repository_ids"))
    depends_on_artifact_ids = normalize_id_list(metadata.get("depends_on_artifact_ids"))
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "artifact_kind": artifact.artifact_kind,
        "title": artifact.title or "",
        "status": artifact.status or "draft",
        "summary": artifact.summary or "",
        "content_markdown": artifact.content_markdown or "",
        "owner_user_id": artifact.owner_user_id,
        "owner_label": (owner_labels or {}).get(str(artifact.owner_user_id or "").strip(), ""),
        "metadata_json": metadata,
        "linked_repository_ids": linked_repository_ids,
        "depends_on_artifact_ids": depends_on_artifact_ids,
        "is_required": bool(artifact.is_required),
        "order_index": int(artifact.order_index or 100),
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def serialize_trace_link(link: DesignArtifactTraceLink) -> dict[str, object]:
    return {
        "id": link.id,
        "project_id": link.project_id,
        "artifact_id": link.artifact_id,
        "target_type": link.target_type,
        "target_id": link.target_id,
        "title": link.title or "",
        "status": link.status or "active",
        "url": link.url or "",
        "metadata_json": normalize_metadata(link.metadata_json),
        "created_by_user_id": link.created_by_user_id,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "updated_at": link.updated_at.isoformat() if link.updated_at else None,
    }
