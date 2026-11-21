"""Overview assembly for admin project quality views."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.design_artifact.crud import list_design_artifacts

from ....models import Project
from ...code_intelligence.repository import (
    list_code_repositories,
)
from ...design_artifact_service import get_project_design_readiness, get_project_design_traceability
from ...design_delivery_sync import (
    get_project_design_trace_sync_workflows,
    list_project_design_trace_sync_templates,
)
from ._admin_project_quality_overview_rows import (
    OverviewRows,
    _overview_error,
    load_overview_rows,
    serialize_project_agents,
    serialize_trace_sync_schedulers,
    serialize_trace_sync_tasks,
)
from .admin_project_quality_catalog import (
    build_project_agent_role_summary,
    normalize_project_agent_preferences,
)
from .admin_project_quality_project import serialize_project

logger = logging.getLogger(__name__)


async def _safe_project_section(
    db: AsyncSession,
    *,
    project_id: str,
    section: str,
    errors: list[dict[str, str]],
    default: Any,
    loader: Callable[[], Awaitable[Any]],
) -> Any:
    try:
        return await loader()
    except Exception as exc:
        logger.exception(
            "Optional admin project overview section failed",
            extra={"project_id": project_id, "section": section},
        )
        errors.append(_overview_error(section, exc))
        if isinstance(exc, SQLAlchemyError):
            await db.rollback()
        return default


async def list_projects_for_quality_config(db: AsyncSession) -> list[dict[str, object]]:
    # Private Workspaces are nobody's to configure but their owner's: the admin list leaves them out.
    projects = (
        (await db.execute(select(Project).where(Project.access_mode != "private").order_by(Project.name.asc())))
        .scalars()
        .all()
    )
    project_entries = [
        (
            project.id,
            dict(project.config or {}) if isinstance(project.config, dict) else {},
            serialize_project(project),
        )
        for project in projects
    ]
    project_ids = [project_id for project_id, _, _ in project_entries]
    overview_errors: list[dict[str, str]] = []
    rows = await load_overview_rows(db, project_ids=project_ids, errors=overview_errors)

    payload: list[dict[str, object]] = []
    for project_id, project_config, base_item in project_entries:
        item = dict(base_item)
        project_errors = list(overview_errors)
        item["overview_errors"] = project_errors
        item["overview_status"] = "partial" if project_errors else "ok"
        agent_preferences = normalize_project_agent_preferences(project_config)
        await _load_design_sections(db, item, project_id=project_id, errors=project_errors)
        await _load_agent_sections(
            db,
            item,
            project_id=project_id,
            agent_preferences=agent_preferences,
            rows=rows,
            errors=project_errors,
        )
        await _load_trace_sync_sections(
            db, item, project_id=project_id, project_config=project_config, rows=rows, errors=project_errors
        )
        item["overview_status"] = "partial" if project_errors else "ok"
        payload.append(item)
    return payload


async def _load_design_sections(
    db: AsyncSession, item: dict[str, Any], *, project_id: str, errors: list[dict[str, str]]
) -> None:
    item["code_repositories"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="code_repositories",
        errors=errors,
        default=[],
        loader=lambda: list_code_repositories(db, project_id=project_id),
    )
    item["design_artifacts"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_artifacts",
        errors=errors,
        default=[],
        loader=lambda: list_design_artifacts(db, project_id=project_id),
    )
    item["design_readiness"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_readiness",
        errors=errors,
        default=item["design_readiness"],
        loader=lambda: get_project_design_readiness(db, project_id=project_id),
    )
    item["design_traceability"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_traceability",
        errors=errors,
        default=item["design_traceability"],
        loader=lambda: get_project_design_traceability(db, project_id=project_id),
    )


async def _load_agent_sections(
    db: AsyncSession,
    item: dict[str, Any],
    *,
    project_id: str,
    agent_preferences: dict[str, dict[str, Any]],
    rows: OverviewRows,
    errors: list[dict[str, str]],
) -> None:
    deduped_agents = await _safe_project_section(
        db,
        project_id=project_id,
        section="project_agent_catalog",
        errors=errors,
        default=[],
        loader=lambda: serialize_project_agents(
            rows.project_agents_by_project.get(project_id, []),
            agent_preferences=agent_preferences,
        ),
    )
    item["project_agent_catalog"] = deduped_agents
    item["project_agent_role_summary"] = build_project_agent_role_summary(deduped_agents)


async def _load_trace_sync_sections(
    db: AsyncSession,
    item: dict[str, Any],
    *,
    project_id: str,
    project_config: dict[str, Any],
    rows: OverviewRows,
    errors: list[dict[str, str]],
) -> None:
    custom_templates = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_trace_sync_custom_templates",
        errors=errors,
        default=[],
        loader=lambda: list_project_design_trace_sync_templates(db, project_id=project_id),
    )
    item["design_trace_sync_custom_templates"] = custom_templates
    item["design_trace_sync_workflows"] = get_project_design_trace_sync_workflows(
        project_config,
        custom_templates=custom_templates,
    )

    trace_tasks = rows.trace_sync_tasks_by_project.get(project_id, [])
    item["design_trace_sync_tasks"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_trace_sync_tasks",
        errors=errors,
        default=[],
        loader=lambda: serialize_trace_sync_tasks(
            db,
            trace_tasks=trace_tasks,
            trace_sync_runs_by_task_id=rows.trace_sync_runs_by_task_id,
        ),
    )
    item["design_trace_sync_schedulers"] = await _safe_project_section(
        db,
        project_id=project_id,
        section="design_trace_sync_schedulers",
        errors=errors,
        default=[],
        loader=lambda: serialize_trace_sync_schedulers(
            trace_tasks=trace_tasks,
            schedulers_by_task_id=rows.schedulers_by_task_id,
        ),
    )


__all__ = [
    "_safe_project_section",
    "list_projects_for_quality_config",
]
