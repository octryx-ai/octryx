"""Coding workspace rows: one per change unit and restart generation, with its path and repository identity."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    CodeRepository,
    User,
    WorkChangePlan,
    WorkCodingWorkspace,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from ....services.session.workspace import get_session_workspace_base_dir
from ....time_utils import utc_now
from ..jira_values import blank_to_none
from .workspace_git import _materialize_local_git_workspace


async def _existing_workspace(
    db: AsyncSession,
    *,
    pipeline_run_id: str,
    change_unit_id: str,
    generation: int,
) -> WorkCodingWorkspace | None:
    return (
        await db.execute(
            select(WorkCodingWorkspace).where(
                WorkCodingWorkspace.pipeline_run_id == pipeline_run_id,
                WorkCodingWorkspace.change_unit_id == change_unit_id,
                WorkCodingWorkspace.restart_generation == generation,
            )
        )
    ).scalar_one_or_none()


async def _deactivate_previous_workspaces(db: AsyncSession, *, item_id: str, current_user: User) -> None:
    rows = (
        await db.execute(
            select(WorkCodingWorkspace).where(
                WorkCodingWorkspace.work_item_id == item_id,
                WorkCodingWorkspace.is_active.is_(True),
            )
        )
    ).scalars().all()
    now = utc_now()
    for row in rows:
        row.is_active = False
        row.updated_by = current_user.id
        row.updated_at = now


async def _next_restart_generation(db: AsyncSession, *, item_id: str) -> int:
    rows = (
        await db.execute(
            select(WorkCodingWorkspace.restart_generation).where(WorkCodingWorkspace.work_item_id == item_id)
        )
    ).scalars().all()
    return (max([int(value or 0) for value in rows], default=0) + 1) if rows else 1


async def _workspace_from_unit(
    db: AsyncSession,
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    unit: WorkItemChangeUnit,
    profile: WorkRepositoryProfile | None,
    code_repository: CodeRepository | None,
    pipeline_run_id: str,
    generation: int,
    current_user: User,
) -> WorkCodingWorkspace:
    repository_name = str(unit.repository_name or (profile.name if profile else "")).strip()
    repository_url = blank_to_none(profile.repository_url if profile else None) or blank_to_none(
        code_repository.remote_url if code_repository else None
    )
    repository_slug = _repository_slug(repository_url, repository_name)
    project_key = _project_key(repository_url, item.source_project_key)
    base_branch = _base_branch(unit, profile, code_repository)
    source_root = _source_repository_root(code_repository)
    workspace_root = await _workspace_path(
        db, source_key=item.source_key, pipeline_run_id=pipeline_run_id, repository_slug=repository_slug
    )
    workspace_root.mkdir(parents=True, exist_ok=True)
    materialized = _materialize_local_git_workspace(
        source_root=source_root,
        workspace_root=workspace_root,
        feature_branch=str(unit.branch_name or "").strip(),
        base_branch=base_branch,
    )
    evidence = _workspace_evidence(unit, profile, code_repository, source_root, workspace_root, materialized)
    return WorkCodingWorkspace(
        work_item_id=item.id,
        pipeline_run_id=pipeline_run_id,
        change_unit_id=unit.id,
        repository_profile_id=unit.repository_profile_id,
        provider=str(profile.provider if profile else "bitbucket").strip()[:50] or "bitbucket",
        provider_instance=str(item.source_instance or "default").strip()[:220] or "default",
        project_key=project_key,
        repository_name=repository_name[:220],
        repository_slug=repository_slug[:220],
        repository_url=repository_url,
        base_branch=base_branch[:260],
        resolved_base_branch=base_branch[:260],
        feature_branch=str(unit.branch_name or "").strip()[:260],
        base_commit=materialized["base_commit"]
        or blank_to_none(code_repository.last_indexed_commit if code_repository else None),
        workspace_path=str(workspace_root),
        source_repository_root=str(source_root) if source_root else None,
        source_evidence_cutoff=plan.approved_at or plan.decided_at or plan.updated_at or plan.created_at,
        restart_generation=generation,
        status=materialized["status"],
        evidence_json=evidence,
        is_active=True,
        created_by=current_user.id,
        updated_by=current_user.id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def _base_branch(
    unit: WorkItemChangeUnit, profile: WorkRepositoryProfile | None, code_repository: CodeRepository | None
) -> str:
    return blank_to_none((unit.reviewer_policy_json or {}).get("target_branch")) or blank_to_none(
        profile.pr_target_branch if profile else None
    ) or blank_to_none(profile.default_branch if profile else None) or blank_to_none(
        code_repository.default_branch if code_repository else None
    ) or "main"


def _workspace_evidence(
    unit: WorkItemChangeUnit,
    profile: WorkRepositoryProfile | None,
    code_repository: CodeRepository | None,
    source_root: Path | None,
    workspace_root: Path,
    materialized: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "secure_work_coding_workspace",
        "repository_profile_id": profile.id if profile else None,
        "code_repository_id": code_repository.id if code_repository else None,
        "source_repository_exists": bool(source_root),
        "workspace_created": workspace_root.exists(),
        **materialized["evidence"],
        "approved_expected_paths": list(unit.expected_paths_json or []),
    }


async def _workspace_path(
    db: AsyncSession,
    *,
    source_key: str,
    pipeline_run_id: str,
    repository_slug: str,
) -> Path:
    base = await get_session_workspace_base_dir(db)
    safe_source = _safe_path_segment(source_key)
    safe_run = _safe_path_segment(pipeline_run_id)
    safe_repo = _safe_path_segment(repository_slug)
    return (base / "coding-runs" / safe_source / safe_run / safe_repo).resolve()


async def _code_repository(db: AsyncSession, repository_id: str | None) -> CodeRepository | None:
    if not repository_id:
        return None
    return await db.get(CodeRepository, repository_id)


def _source_repository_root(code_repository: CodeRepository | None) -> Path | None:
    if code_repository is None or not code_repository.repo_root:
        return None
    root = Path(str(code_repository.repo_root)).expanduser().resolve()
    return root if root.exists() and root.is_dir() else None


def _repository_slug(repository_url: str | None, fallback: str) -> str:
    text = str(repository_url or "").strip()
    for pattern in (r"/repos/([^/?#]+)", r"/([^/]+?)(?:\.git)?$"):
        match = re.search(pattern, text)
        if match:
            return _safe_slug(match.group(1))
    return _safe_slug(fallback) or "repository"


def _project_key(repository_url: str | None, fallback: str | None) -> str | None:
    text = str(repository_url or "").strip()
    match = re.search(r"/projects/([^/]+)/repos/", text)
    if match:
        return match.group(1)
    return blank_to_none(fallback)


def _safe_slug(value: str) -> str:
    return _safe_path_segment(value).lower()


def _safe_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    return re.sub(r"-+", "-", text).strip(".-_")[:160]
