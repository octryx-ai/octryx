"""Generic project template import contract."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User, UserProject
from app.services.trace_capture import ensure_default_trace_capture_config

PROJECT_SOURCE_SYSTEM = "system"
PROJECT_SOURCE_MANUAL = "manual"
PROJECT_SOURCE_TEMPLATE = "template"
PROJECT_SOURCE_SAMPLE = "sample"
DEFAULT_PROJECT_NAME = "default"

ALLOWED_PROJECT_SOURCE_TYPES = {
    PROJECT_SOURCE_SYSTEM,
    PROJECT_SOURCE_MANUAL,
    PROJECT_SOURCE_TEMPLATE,
    PROJECT_SOURCE_SAMPLE,
}


@dataclass(frozen=True)
class ProjectTemplateSpec:
    """Validated, data-only project template definition."""

    template_key: str
    display_name: str
    version: str
    description: str | None = None
    project_name: str | None = None
    project_description: str | None = None
    project_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = PROJECT_SOURCE_TEMPLATE

    def validate(self) -> None:
        if not self.template_key.strip():
            raise ValueError("template_key is required")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if not self.version.strip():
            raise ValueError("version is required")
        if self.source_type not in ALLOWED_PROJECT_SOURCE_TYPES:
            raise ValueError(f"unsupported project source type: {self.source_type}")
        if not isinstance(self.project_config, dict):
            raise ValueError("project_config must be an object")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")

    @property
    def resolved_project_name(self) -> str:
        return (self.project_name or self.template_key).strip()

    @property
    def resolved_project_description(self) -> str:
        return (self.project_description or self.description or self.display_name).strip()


async def import_project_template(
    db: AsyncSession,
    *,
    template: ProjectTemplateSpec,
    admin_user: User,
    overwrite_config: bool = False,
) -> Project:
    """Create or update a project from a template without hiding its source."""

    template.validate()
    project_name = template.resolved_project_name
    existing = (await db.execute(select(Project).where(Project.name == project_name))).scalar_one_or_none()
    template_metadata = {
        **template.metadata,
        "template_display_name": template.display_name,
    }

    if existing is None:
        project = Project(
            id=str(uuid.uuid4()),
            name=project_name,
            description=template.resolved_project_description,
            config=ensure_default_trace_capture_config(template.project_config),
            source_type=template.source_type,
            template_key=template.template_key,
            template_version=template.version,
            template_metadata=template_metadata,
            is_system=template.source_type == PROJECT_SOURCE_SYSTEM,
            is_active=True,
        )
        db.add(project)
        await db.flush()
        db.add(UserProject(user_id=admin_user.id, project_id=project.id, role="owner"))
        return project

    existing.description = existing.description or template.resolved_project_description
    if overwrite_config:
        existing.config = ensure_default_trace_capture_config(template.project_config)
    else:
        existing.config = ensure_default_trace_capture_config(existing.config)
    existing.source_type = template.source_type
    existing.template_key = template.template_key
    existing.template_version = template.version
    existing.template_metadata = {
        **(existing.template_metadata if isinstance(existing.template_metadata, dict) else {}),
        **template_metadata,
    }
    existing.is_system = bool(existing.is_system or template.source_type == PROJECT_SOURCE_SYSTEM)

    assigned = (
        await db.execute(
            select(UserProject).where(
                UserProject.user_id == admin_user.id,
                UserProject.project_id == existing.id,
            )
        )
    ).scalar_one_or_none()
    if assigned is None:
        db.add(UserProject(user_id=admin_user.id, project_id=existing.id, role="owner"))
    return existing


async def ensure_default_project(db: AsyncSession, *, admin_user: User) -> Project:
    """Ensure the generic protected project that every fresh deployment needs."""

    template = ProjectTemplateSpec(
        template_key="system-default-project",
        display_name="Default Project",
        version="1",
        project_name=DEFAULT_PROJECT_NAME,
        project_description="Generic default project for shared platform work.",
        project_config={},
        metadata={"protected": True},
        source_type=PROJECT_SOURCE_SYSTEM,
    )
    project = await import_project_template(db, template=template, admin_user=admin_user)
    project.description = template.resolved_project_description
    project.is_active = True
    project.is_system = True
    return project
