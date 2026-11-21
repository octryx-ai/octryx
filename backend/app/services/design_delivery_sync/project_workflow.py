"""Look up one trace sync workflow of a project, built-in or custom template."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from .workflows import get_project_design_trace_sync_workflows, list_project_design_trace_sync_templates


async def load_project_workflow(db: AsyncSession, *, project_id: str, workflow_id: str) -> dict[str, Any]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")
    custom_templates = await list_project_design_trace_sync_templates(db, project_id=project_id)
    workflows = get_project_design_trace_sync_workflows(
        dict(project.config or {}) if isinstance(project.config, dict) else {},
        custom_templates=custom_templates,
    )
    workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if workflow is None:
        raise ValueError("Trace sync workflow not found")
    return workflow
