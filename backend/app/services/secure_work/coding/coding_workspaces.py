from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    User,
    WorkChangePlan,
    WorkCodingPipelineRun,
    WorkCodingWorkspace,
    WorkItem,
    WorkItemChangeUnit,
)
from ....time_utils import utc_now
from ...prompt_catalog import render_prompt
from ..coding_serializers import serialize_coding_workspace
from ..jira_values import blank_to_none
from ..related_rows import REPOSITORY_PROFILE, load_optional_related
from .workspace_records import (
    _code_repository,
    _deactivate_previous_workspaces,
    _existing_workspace,
    _next_restart_generation,
    _workspace_from_unit,
)


async def prepare_coding_workspaces(
    db: AsyncSession,
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    units: list[WorkItemChangeUnit],
    pipeline_run_id: str,
    current_user: User,
    restart_from_scratch: bool = False,
) -> list[dict[str, Any]]:
    run = await db.get(WorkCodingPipelineRun, pipeline_run_id)
    if run is None:
        return []
    if restart_from_scratch:
        await _deactivate_previous_workspaces(db, item_id=item.id, current_user=current_user)
    generation = await _next_restart_generation(db, item_id=item.id) if restart_from_scratch else 0
    prepared: list[WorkCodingWorkspace] = []
    for unit in units:
        existing = await _existing_workspace(
            db,
            pipeline_run_id=pipeline_run_id,
            change_unit_id=unit.id,
            generation=generation,
        )
        if existing is not None:
            prepared.append(existing)
            continue
        # The unit's stored profile, as the caller may use it for this item (``related_rows``).
        profile = await load_optional_related(db, current_user, REPOSITORY_PROFILE, unit.repository_profile_id,
                                              for_workspace=item.project_id)
        code_repository = await _code_repository(db, profile.code_repository_id if profile else None)
        row = await _workspace_from_unit(
            db,
            item=item,
            plan=plan,
            unit=unit,
            profile=profile,
            code_repository=code_repository,
            pipeline_run_id=pipeline_run_id,
            generation=generation,
            current_user=current_user,
        )
        db.add(row)
        prepared.append(row)
    await db.flush()
    return [serialize_coding_workspace(row) for row in prepared]


async def attach_workspace_session(
    db: AsyncSession,
    *,
    workspace_ids: list[str],
    session_id: str,
    current_user: User,
) -> list[dict[str, Any]]:
    if not workspace_ids:
        return []
    rows = (
        await db.execute(select(WorkCodingWorkspace).where(WorkCodingWorkspace.id.in_(workspace_ids)))
    ).scalars().all()
    for row in rows:
        row.session_id = session_id
        row.updated_by = current_user.id
        row.updated_at = utc_now()
    await db.flush()
    return [serialize_coding_workspace(row) for row in rows]


async def record_bitbucket_prepare_result(
    db: AsyncSession,
    *,
    session_id: str,
    current_user_id: str,
    result: dict[str, Any],
) -> dict[str, Any] | None:
    if not session_id or result.get("error"):
        return None
    local_path = blank_to_none(result.get("local_path"))
    project_key = blank_to_none(result.get("project_key"))
    repo_slug = blank_to_none(result.get("repo_slug"))
    branch_name = blank_to_none(result.get("branch_name"))
    if not local_path or not repo_slug:
        return None
    rows = (
        await db.execute(
            select(WorkCodingWorkspace).where(
                WorkCodingWorkspace.session_id == session_id,
                WorkCodingWorkspace.is_active.is_(True),
            )
        )
    ).scalars().all()
    workspace = _matching_workspace(
        rows,
        project_key=project_key,
        repo_slug=repo_slug,
        branch_name=branch_name,
    )
    if workspace is None:
        return None
    evidence = dict(workspace.evidence_json or {})
    evidence["prepare_bitbucket_repository"] = _prepare_result_evidence(result)
    evidence["clone_performed"] = True
    evidence["clone_reason"] = "prepare_bitbucket_repository_tool"
    workspace.workspace_path = local_path
    workspace.base_commit = blank_to_none(result.get("head_commit")) or workspace.base_commit
    workspace.resolved_base_branch = blank_to_none(result.get("base_branch")) or workspace.resolved_base_branch
    workspace.feature_branch = branch_name or workspace.feature_branch
    workspace.status = "prepared"
    workspace.evidence_json = evidence
    workspace.updated_by = current_user_id
    workspace.updated_at = utc_now()
    await db.flush()
    return serialize_coding_workspace(workspace)


def primary_workspace_root(workspaces: list[dict[str, Any]]) -> str:
    for workspace in workspaces:
        path = str(workspace.get("workspace_path") or "").strip()
        status = str(workspace.get("status") or "").strip()
        if path and status in {"prepared", "prepared_empty"}:
            return path
    return ""


def workspace_metadata_patch(workspaces: list[dict[str, Any]]) -> dict[str, Any]:
    primary_root = primary_workspace_root(workspaces)
    patch: dict[str, Any] = {"coding_workspace_records": workspaces}
    if primary_root:
        patch["secure_work_execution_workspace"] = {
            "primary_workspace_root": primary_root,
            "workspace_ids": [str(workspace.get("id") or "") for workspace in workspaces if workspace.get("id")],
        }
    return patch


def workspace_prompt_lines(workspaces: list[dict[str, Any]]) -> list[str]:
    if not workspaces:
        return [render_prompt("secure_work.workspace.none_prepared")]
    lines: list[str] = []
    for workspace in workspaces:
        lines.append(
            "- "
            f"{workspace.get('repository_slug') or workspace.get('repository_name')} "
            f"project {workspace.get('project_key') or '-'} "
            f"branch {workspace.get('feature_branch') or '-'} "
            f"base {workspace.get('resolved_base_branch') or workspace.get('base_branch') or '-'} "
            f"at {workspace.get('workspace_path') or '-'} "
            f"({workspace.get('status') or 'unknown'})"
        )
        if str(workspace.get("status") or "") == "prepared_empty" and workspace.get("project_key"):
            lines.append(
                "  prepare: "
                f"prepare_bitbucket_repository(project_key={workspace.get('project_key')}, "
                f"repo_slug={workspace.get('repository_slug')}, "
                f"base_branch={workspace.get('resolved_base_branch') or workspace.get('base_branch') or ''}, "
                f"branch_name={workspace.get('feature_branch') or ''})"
            )
    return lines


def _matching_workspace(
    rows: list[WorkCodingWorkspace],
    *,
    project_key: str | None,
    repo_slug: str,
    branch_name: str | None,
) -> WorkCodingWorkspace | None:
    candidates = [row for row in rows if _same_text(row.repository_slug, repo_slug)]
    if project_key:
        project_matches = [row for row in candidates if _same_text(row.project_key, project_key)]
        if project_matches:
            candidates = project_matches
    if branch_name:
        branch_matches = [row for row in candidates if _same_text(row.feature_branch, branch_name)]
        if branch_matches:
            candidates = branch_matches
    return candidates[0] if len(candidates) == 1 else None


def _prepare_result_evidence(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "project_key",
            "repo_slug",
            "local_path",
            "relative_path",
            "base_branch",
            "branch_name",
            "cloned",
            "fallback_used",
            "attempted_base_branches",
            "remote_url",
            "head_commit",
        )
        if key in result
    }


def _same_text(left: str | None, right: str | None) -> bool:
    return str(left or "").strip().lower() == str(right or "").strip().lower()


__all__ = [
    "attach_workspace_session",
    "prepare_coding_workspaces",
    "primary_workspace_root",
    "record_bitbucket_prepare_result",
    "workspace_metadata_patch",
    "workspace_prompt_lines",
]
