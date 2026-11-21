"""CRUD operations for design artifacts and trace links."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.design_artifact.common import (
    merge_artifact_metadata,
    normalize_artifact_kind,
    normalize_artifact_status,
    normalize_metadata,
    normalize_trace_status,
    normalize_trace_target_type,
)
from app.services.design_artifact.serialization import serialize_design_artifact, serialize_trace_link
from app.services.design_artifact.support import (
    project_exists,
    user_label_map,
    validate_trace_target,
)

from ...models import DesignArtifact, DesignArtifactTraceLink


async def list_design_artifacts(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_kind: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    await project_exists(db, project_id)
    stmt = select(DesignArtifact).where(DesignArtifact.project_id == project_id)
    normalized_kind = normalize_artifact_kind(artifact_kind) if artifact_kind else ""
    normalized_status = normalize_artifact_status(status) if status else ""
    if normalized_kind:
        stmt = stmt.where(DesignArtifact.artifact_kind == normalized_kind)
    if normalized_status:
        stmt = stmt.where(DesignArtifact.status == normalized_status)
    stmt = stmt.order_by(
        DesignArtifact.order_index.asc(),
        DesignArtifact.updated_at.desc(),
        DesignArtifact.created_at.asc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    owner_labels = await user_label_map(
        db,
        {str(item.owner_user_id or "").strip() for item in rows if item.owner_user_id},
    )
    return [serialize_design_artifact(item, owner_labels=owner_labels) for item in rows]


async def create_design_artifact(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    await project_exists(db, project_id)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    artifact = DesignArtifact(
        id=str(uuid.uuid4()),
        project_id=project_id,
        artifact_kind=normalize_artifact_kind(payload.get("artifact_kind")),
        title=title,
        status=normalize_artifact_status(payload.get("status")),
        summary=str(payload.get("summary") or "").strip() or None,
        content_markdown=str(payload.get("content_markdown") or payload.get("content") or "").strip(),
        owner_user_id=str(payload.get("owner_user_id") or "").strip() or None,
        metadata_json=merge_artifact_metadata(payload),
        is_required=bool(payload.get("is_required", False)),
        order_index=max(0, int(payload.get("order_index") or 100)),
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    owner_labels = await user_label_map(db, {artifact.owner_user_id} if artifact.owner_user_id else set())
    return serialize_design_artifact(artifact, owner_labels=owner_labels)


async def update_design_artifact(
    db: AsyncSession,
    *,
    artifact_id: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    artifact = await db.get(DesignArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Design artifact not found")

    if "artifact_kind" in payload:
        artifact.artifact_kind = normalize_artifact_kind(payload.get("artifact_kind"))
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        artifact.title = title
    if "status" in payload:
        artifact.status = normalize_artifact_status(payload.get("status"))
    if "summary" in payload:
        artifact.summary = str(payload.get("summary") or "").strip() or None
    if "content_markdown" in payload or "content" in payload:
        artifact.content_markdown = str(payload.get("content_markdown") or payload.get("content") or "").strip()
    if "owner_user_id" in payload:
        artifact.owner_user_id = str(payload.get("owner_user_id") or "").strip() or None
    if "metadata_json" in payload:
        artifact.metadata_json = merge_artifact_metadata(payload)
    elif "linked_repository_ids" in payload or "depends_on_artifact_ids" in payload:
        current_payload = {
            "metadata_json": normalize_metadata(artifact.metadata_json),
            "linked_repository_ids": payload.get("linked_repository_ids"),
            "depends_on_artifact_ids": payload.get("depends_on_artifact_ids"),
        }
        artifact.metadata_json = merge_artifact_metadata(current_payload)
    if "is_required" in payload:
        artifact.is_required = bool(payload.get("is_required"))
    if "order_index" in payload:
        artifact.order_index = max(0, int(payload.get("order_index") or 100))

    await db.commit()
    await db.refresh(artifact)
    owner_labels = await user_label_map(db, {artifact.owner_user_id} if artifact.owner_user_id else set())
    return serialize_design_artifact(artifact, owner_labels=owner_labels)


async def delete_design_artifact(db: AsyncSession, *, artifact_id: str) -> dict[str, object]:
    artifact = await db.get(DesignArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Design artifact not found")
    await db.delete(artifact)
    await db.commit()
    return {"ok": True, "artifact_id": artifact_id}


async def list_design_trace_links(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_id: str | None = None,
) -> list[dict[str, object]]:
    await project_exists(db, project_id)
    stmt = select(DesignArtifactTraceLink).where(DesignArtifactTraceLink.project_id == project_id)
    if artifact_id:
        stmt = stmt.where(DesignArtifactTraceLink.artifact_id == artifact_id)
    stmt = stmt.order_by(DesignArtifactTraceLink.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_trace_link(row) for row in rows]


async def create_design_trace_link(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, Any],
    created_by_user_id: str | None = None,
) -> dict[str, object]:
    await project_exists(db, project_id)
    artifact_id = str(payload.get("artifact_id") or "").strip()
    artifact = await db.get(DesignArtifact, artifact_id)
    if not artifact or str(artifact.project_id or "") != project_id:
        raise HTTPException(status_code=400, detail="artifact_id must belong to the same project")
    target_type = normalize_trace_target_type(payload.get("target_type"))
    target_id = str(payload.get("target_id") or "").strip() or None
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    url = str(payload.get("url") or "").strip() or None
    if target_type in {"pull_request", "release"} and not (target_id or url):
        raise HTTPException(status_code=400, detail="pull_request and release links require target_id or url")
    await validate_trace_target(db, project_id=project_id, target_type=target_type, target_id=target_id)
    link = DesignArtifactTraceLink(
        id=str(uuid.uuid4()),
        project_id=project_id,
        artifact_id=artifact_id,
        target_type=target_type,
        target_id=target_id,
        title=title,
        status=normalize_trace_status(payload.get("status")),
        url=url,
        metadata_json=normalize_metadata(payload.get("metadata_json")),
        created_by_user_id=str(created_by_user_id or payload.get("created_by_user_id") or "").strip() or None,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return serialize_trace_link(link)


async def delete_design_trace_link(db: AsyncSession, *, link_id: str) -> dict[str, object]:
    link = await db.get(DesignArtifactTraceLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Design trace link not found")
    await db.delete(link)
    await db.commit()
    return {"ok": True, "link_id": link_id}


def _task_payload_from_artifact(
    artifact: DesignArtifact, raw_payload: dict[str, Any], *, project_id: str, title: str
) -> dict[str, Any]:
    summary = str(artifact.summary or "").strip()
    content = str(artifact.content_markdown or "").strip()
    description = str(raw_payload.get("description") or "").strip()
    if not description:
        description_parts = [part for part in [summary, content[:600].strip()] if part]
        description = "\n\n".join(description_parts).strip()
    agent_type = str(raw_payload.get("agent_type") or "").strip() or "coding"
    return {
        "project_id": project_id,
        "name": title,
        "description": description,
        "task_type": str(raw_payload.get("task_type") or "agent_run"),
        "agent_type": agent_type,
        "schedule": raw_payload.get("schedule"),
        "config": {
            **(raw_payload.get("config") if isinstance(raw_payload.get("config"), dict) else {}),
            "source_design_artifact_id": artifact.id,
            "source_design_artifact_kind": artifact.artifact_kind,
        },
        "max_concurrent_agents": int(raw_payload.get("max_concurrent_agents") or 3),
        "is_active": bool(raw_payload.get("is_active", True)),
        # Required and validated by create_task; never defaulted here.
        "dispatch_binding": raw_payload.get("dispatch_binding"),
    }


async def create_task_from_design_artifact(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_id: str,
    user_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    await project_exists(db, project_id)
    artifact = await db.get(DesignArtifact, artifact_id)
    if not artifact or str(artifact.project_id or "") != project_id:
        raise HTTPException(status_code=404, detail="Design artifact not found")

    from app.services.admin.task._admin_task_management import create_task

    raw_payload = dict(payload or {})
    title = str(raw_payload.get("name") or artifact.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task name could not be derived from artifact")
    task = await create_task(
        db,
        user_id=user_id,
        payload=_task_payload_from_artifact(artifact, raw_payload, project_id=project_id, title=title),
    )
    link = await create_design_trace_link(
        db,
        project_id=project_id,
        payload={
            "artifact_id": artifact.id,
            "target_type": "task",
            "target_id": task["id"],
            "title": title,
            "status": "active",
            "metadata_json": {"auto_created": True},
        },
        created_by_user_id=user_id,
    )
    return {
        "project_id": project_id,
        "artifact": serialize_design_artifact(artifact),
        "task": task,
        "trace_link": link,
    }
