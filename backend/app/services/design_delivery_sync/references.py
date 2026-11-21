"""Reference lookup helpers for design delivery sync."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DesignArtifactTraceLink, Task


async def artifact_task_titles(db: AsyncSession, artifact_ids: set[str]) -> dict[str, list[str]]:
    if not artifact_ids:
        return {}
    link_rows = (
        await db.execute(
            select(DesignArtifactTraceLink.artifact_id, DesignArtifactTraceLink.target_id).where(
                DesignArtifactTraceLink.artifact_id.in_(sorted(artifact_ids)),
                DesignArtifactTraceLink.target_type == "task",
                DesignArtifactTraceLink.target_id.is_not(None),
            )
        )
    ).all()
    task_ids = {str(row[1]) for row in link_rows if row and row[1]}
    task_titles: dict[str, str] = {}
    if task_ids:
        task_rows = (await db.execute(select(Task.id, Task.name).where(Task.id.in_(sorted(task_ids))))).all()
        task_titles = {str(row[0]): str(row[1] or "") for row in task_rows if row and row[0]}
    by_artifact: dict[str, list[str]] = {}
    for row in link_rows:
        artifact_id = str(row[0] or "")
        task_id = str(row[1] or "")
        title = task_titles.get(task_id, "").strip()
        if artifact_id and title:
            by_artifact.setdefault(artifact_id, []).append(title)
    return by_artifact


async def artifact_pull_request_refs(db: AsyncSession, artifact_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    if not artifact_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DesignArtifactTraceLink.artifact_id,
                DesignArtifactTraceLink.title,
                DesignArtifactTraceLink.target_id,
                DesignArtifactTraceLink.metadata_json,
            ).where(
                DesignArtifactTraceLink.artifact_id.in_(sorted(artifact_ids)),
                DesignArtifactTraceLink.target_type == "pull_request",
            )
        )
    ).all()
    by_artifact: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        artifact_id = str(row[0] or "")
        if not artifact_id:
            continue
        metadata = row[3] if isinstance(row[3], dict) else {}
        by_artifact.setdefault(artifact_id, []).append(
            {
                "title": str(row[1] or ""),
                "target_id": str(row[2] or ""),
                "number": metadata.get("number"),
                "provider": metadata.get("provider"),
                "repository_name": metadata.get("repository_name"),
            }
        )
    return by_artifact


async def artifact_release_refs(db: AsyncSession, artifact_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    if not artifact_ids:
        return {}
    rows = (
        await db.execute(
            select(
                DesignArtifactTraceLink.artifact_id,
                DesignArtifactTraceLink.title,
                DesignArtifactTraceLink.target_id,
                DesignArtifactTraceLink.metadata_json,
            ).where(
                DesignArtifactTraceLink.artifact_id.in_(sorted(artifact_ids)),
                DesignArtifactTraceLink.target_type == "release",
            )
        )
    ).all()
    by_artifact: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        artifact_id = str(row[0] or "")
        if not artifact_id:
            continue
        metadata = row[3] if isinstance(row[3], dict) else {}
        by_artifact.setdefault(artifact_id, []).append(
            {
                "title": str(row[1] or ""),
                "target_id": str(row[2] or ""),
                "tag_name": str(metadata.get("tag_name") or ""),
                "provider": metadata.get("provider"),
                "repository_name": metadata.get("repository_name"),
            }
        )
    return by_artifact
