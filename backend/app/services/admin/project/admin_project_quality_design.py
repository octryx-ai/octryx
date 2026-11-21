"""Design and traceability helpers for admin project quality endpoints."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.design_artifact.common import list_recommended_design_artifacts
from app.services.design_artifact.crud import (
    create_design_artifact,
    create_design_trace_link,
    create_task_from_design_artifact,
    delete_design_artifact,
    delete_design_trace_link,
    list_design_artifacts,
    list_design_trace_links,
    update_design_artifact,
)

from ....models import Project
from ...design_artifact_service import (
    bootstrap_design_artifacts,
    get_project_design_readiness,
    get_project_design_traceability,
)
from ...design_delivery_sync import (
    create_design_trace_sync_workflow_task,
    delete_project_design_trace_sync_template,
    get_project_design_trace_sync_workflows,
    list_design_trace_sync_templates,
    list_project_design_trace_sync_templates,
    run_design_trace_sync_workflow,
    sync_checkpoint_traceability,
    sync_release_traceability,
    update_project_design_trace_sync_workflows,
    upsert_project_design_trace_sync_template,
)
from ...design_delivery_sync.workflows import WORKFLOW_IDS


async def list_project_design_artifacts(db: AsyncSession, *, project_id: str) -> dict[str, object]:
    return {
        "items": await list_design_artifacts(db, project_id=project_id),
        "templates": list_recommended_design_artifacts(),
    }


async def create_project_design_artifact(
    db: AsyncSession, *, project_id: str, payload: dict[str, object]
) -> dict[str, object]:
    return await create_design_artifact(db, project_id=project_id, payload=payload)


async def list_project_design_trace_links(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_id: str | None = None,
) -> dict[str, object]:
    return {"items": await list_design_trace_links(db, project_id=project_id, artifact_id=artifact_id)}


async def create_project_design_trace_link(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, object],
    created_by_user_id: str | None = None,
) -> dict[str, object]:
    return await create_design_trace_link(
        db, project_id=project_id, payload=payload, created_by_user_id=created_by_user_id
    )


async def create_project_task_from_design_artifact(
    db: AsyncSession,
    *,
    project_id: str,
    artifact_id: str,
    user_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return await create_task_from_design_artifact(
        db, project_id=project_id, artifact_id=artifact_id, user_id=user_id, payload=payload
    )


async def sync_project_design_releases(
    db: AsyncSession, *, project_id: str, limit_per_repository: int
) -> dict[str, object]:
    return await sync_release_traceability(db, project_id=project_id, limit_per_repository=limit_per_repository)


async def sync_project_design_checkpoints(
    db: AsyncSession, *, project_id: str, limit_per_repository: int
) -> dict[str, object]:
    return await sync_checkpoint_traceability(db, project_id=project_id, limit_per_repository=limit_per_repository)


async def list_project_design_trace_sync_workflows(db: AsyncSession, *, project_id: str) -> dict[str, object]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = dict(project.config or {}) if isinstance(project.config, dict) else {}
    custom_templates = await list_project_design_trace_sync_templates(db, project_id=project_id)
    return {
        "templates": list_design_trace_sync_templates(),
        "custom_templates": custom_templates,
        "items": get_project_design_trace_sync_workflows(config, custom_templates=custom_templates),
    }


async def update_project_design_trace_sync_workflows_config(
    db: AsyncSession,
    *,
    project_id: str,
    workflows: list[dict[str, object]],
) -> dict[str, object]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    custom_payloads = [
        item
        for item in workflows
        if str(item.get("id") or "").strip() not in WORKFLOW_IDS
    ]
    for payload in custom_payloads:
        await upsert_project_design_trace_sync_template(db, project_id=project_id, payload=payload)
    items = await update_project_design_trace_sync_workflows(db, project_id=project_id, workflows=workflows)
    custom_templates = await list_project_design_trace_sync_templates(db, project_id=project_id)
    return {
        "templates": list_design_trace_sync_templates(),
        "custom_templates": custom_templates,
        "items": get_project_design_trace_sync_workflows(
            {"design_trace_sync_workflows": items}, custom_templates=custom_templates
        ),
    }


async def run_project_design_trace_sync_workflow(
    db: AsyncSession,
    *,
    project_id: str,
    workflow_id: str,
    limit_per_repository: int | None = None,
) -> dict[str, object]:
    try:
        return await run_design_trace_sync_workflow(
            db, project_id=project_id, workflow_id=workflow_id, limit_per_repository=limit_per_repository
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def upsert_project_design_trace_sync_template_entry(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    try:
        return await upsert_project_design_trace_sync_template(db, project_id=project_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def delete_project_design_trace_sync_template_entry(
    db: AsyncSession,
    *,
    project_id: str,
    template_id: str,
) -> dict[str, object]:
    try:
        return await delete_project_design_trace_sync_template(db, project_id=project_id, template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def create_project_design_trace_sync_workflow_task_instance(
    db: AsyncSession,
    *,
    project_id: str,
    workflow_id: str,
    user_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    try:
        return await create_design_trace_sync_workflow_task(
            db, project_id=project_id, workflow_id=workflow_id, user_id=user_id, payload=payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def delete_project_design_trace_link(db: AsyncSession, *, link_id: str) -> dict[str, object]:
    return await delete_design_trace_link(db, link_id=link_id)


async def bootstrap_project_design_artifacts(
    db: AsyncSession, *, project_id: str, include_optional: bool
) -> dict[str, object]:
    return await bootstrap_design_artifacts(db, project_id=project_id, include_optional=include_optional)


async def get_project_design_readiness_summary(db: AsyncSession, *, project_id: str) -> dict[str, object]:
    return await get_project_design_readiness(db, project_id=project_id)


async def get_project_design_traceability_summary(db: AsyncSession, *, project_id: str) -> dict[str, object]:
    return await get_project_design_traceability(db, project_id=project_id)


async def update_project_design_artifact(
    db: AsyncSession, *, artifact_id: str, payload: dict[str, object]
) -> dict[str, object]:
    return await update_design_artifact(db, artifact_id=artifact_id, payload=payload)


async def delete_project_design_artifact(db: AsyncSession, *, artifact_id: str) -> dict[str, object]:
    return await delete_design_artifact(db, artifact_id=artifact_id)
