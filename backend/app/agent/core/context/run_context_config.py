"""Project-config assembly during run preparation.

Extracted from ``run_context.prepare_agent_run`` as the second seam of the
run-context decomposition: this module owns how a runtime turn assembles the
effective project configuration — project role and user roles, workspace root
resolution (including Engineering Knowledge and Secure Work overrides), the
Secure Work repository patch, workspace execution view tool-policy merging,
and the corp identity / engineering runtime resolution passthroughs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....services.access_control import get_project_role_for_user
from ....services.project import get_project_config, get_user_project_ids
from ....services.workflow_runs.phase_workspace import (
    RUN_BASE_SHA_KEY,
    RUN_WORKING_COPY_KEY,
    phase_working_copy,
)
from ....services.workspace_root_service import resolve_app_workspace_root


def _resolved_engineering_tool_workspace_root(
    engineering_runtime_metadata: dict[str, Any] | None,
) -> Path | None:
    """Return the registered repository root selected by Engineering Knowledge runtime resolution."""

    if not isinstance(engineering_runtime_metadata, dict):
        return None
    blocker_codes = {
        str((blocker or {}).get("code") or "").strip()
        for blocker in engineering_runtime_metadata.get("blockers") or []
        if isinstance(blocker, dict)
    }
    allowed_repository_blockers = {"missing_engineering_knowledge_pack", "stale_engineering_knowledge_pack"}
    if blocker_codes and not blocker_codes.issubset(allowed_repository_blockers):
        return None
    prompt_contract = engineering_runtime_metadata.get("prompt_contract")
    if not isinstance(prompt_contract, dict) or prompt_contract.get("intent") != "coding_migration":
        return None
    repository = engineering_runtime_metadata.get("repository")
    if not isinstance(repository, dict):
        return None
    repository_id = str(repository.get("id") or "").strip()
    repo_root = str(repository.get("repo_root") or "").strip()
    if not repository_id or repository_id.startswith("local:") or not repo_root:
        return None

    root = Path(repo_root).expanduser().resolve()
    return root if root.exists() and root.is_dir() else None


def _resolved_secure_work_tool_workspace_root(session_metadata: dict[str, Any]) -> Path | None:
    """Return the runtime workspace prepared by a governed Secure Work coding run."""

    secure_workspace = session_metadata.get("secure_work_execution_workspace")
    if not isinstance(secure_workspace, dict):
        return None
    root_text = str(secure_workspace.get("primary_workspace_root") or "").strip()
    if not root_text:
        return None
    root = Path(root_text).expanduser().resolve()
    return root if root.exists() and root.is_dir() else None


def _secure_work_project_config_patch(session_metadata: dict[str, Any]) -> dict[str, Any]:
    """Expose approved Secure Work repository coordinates to repository tools."""

    records = session_metadata.get("coding_workspace_records")
    if not isinstance(records, list):
        return {}
    allowed_repos: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        project_key = str(record.get("project_key") or "").strip()
        repo_slug = str(record.get("repository_slug") or "").strip()
        if not project_key or not repo_slug:
            continue
        marker = (project_key.lower(), repo_slug.lower())
        if marker in seen:
            continue
        seen.add(marker)
        allowed_repos.append(
            {
                "project_key": project_key,
                "repo_slug": repo_slug,
                "enabled": True,
                "label": str(record.get("repository_name") or f"{project_key}/{repo_slug}").strip(),
                "source": "secure_work_coding_workspace",
            }
        )
    if not allowed_repos:
        return {}
    return {
        "bitbucket_allowed_repos": allowed_repos,
        "managed_repo_root": "var/repos/bitbucket",
        "secure_work_coding_workspaces": records,
    }


def _with_secure_work_repositories(project_config: dict[str, Any], session_metadata: dict[str, Any]) -> dict[str, Any]:
    """Add the approved Secure Work repositories to the allowed Bitbucket repositories."""
    secure_work_config_patch = _secure_work_project_config_patch(session_metadata)
    if secure_work_config_patch:
        existing_allowed_repos = project_config.get("bitbucket_allowed_repos")
        merged_allowed_repos = [
            *(
                list(existing_allowed_repos)
                if isinstance(existing_allowed_repos, list)
                else []
            ),
            *secure_work_config_patch["bitbucket_allowed_repos"],
        ]
        project_config = {
            **project_config,
            **secure_work_config_patch,
            "bitbucket_allowed_repos": merged_allowed_repos,
        }
    return project_config


def _with_workspace_execution_view(project_config: dict[str, Any], session_metadata: dict[str, Any]) -> dict[str, Any]:
    """Attach the Workspace execution view and merge its tool policy over the project's."""
    workspace_execution_view = session_metadata.get("workspace_execution_view")
    if isinstance(workspace_execution_view, dict) and workspace_execution_view:
        workspace_runtime_policy = (
            workspace_execution_view.get("runtime_policy")
            if isinstance(workspace_execution_view.get("runtime_policy"), dict)
            else {}
        )
        workspace_tool_policy = (
            workspace_runtime_policy.get("tool_policy")
            if isinstance(workspace_runtime_policy.get("tool_policy"), dict)
            else {}
        )
        merged_tool_policy = (
            {
                **(
                    project_config.get("tool_policy")
                    if isinstance(project_config.get("tool_policy"), dict)
                    else {}
                ),
                **workspace_tool_policy,
            }
            if workspace_tool_policy
            else project_config.get("tool_policy")
        )
        project_config = {
            **project_config,
            "workspace_execution_view": workspace_execution_view,
        }
        if isinstance(merged_tool_policy, dict) and merged_tool_policy:
            project_config["tool_policy"] = merged_tool_policy
    return project_config


async def _project_config_with_roles(
    db: AsyncSession, *, user_id: str, project_id: str | None, user_roles: list[str]
) -> dict[str, Any]:
    project_config = await get_project_config(project_id, db)
    if project_id:
        project_role = await get_project_role_for_user(db, user_id, project_id)
        project_config = {
            **project_config,
            "project_id": project_id,
            "project_role": project_role or "",
            "user_roles": user_roles,
        }
    return project_config


@dataclass(frozen=True, slots=True)
class TurnProjectConfig:
    """Assembled project configuration for a turn.

    Fields are exactly the locals the rest of ``prepare_agent_run`` consumes
    after the assembly seam: the merged ``project_config`` mapping, the
    caller's project id scope, and the workspace root that repository/system
    tools operate against.
    """

    project_config: dict[str, Any]
    user_project_ids: list[str]
    tool_workspace_root: Path


async def assemble_turn_project_config(
    *,
    db: AsyncSession,
    user_id: str,
    project_id: str | None,
    user_roles: list[str],
    workspace_root: str,
    session_metadata: dict[str, Any],
    engineering_runtime_metadata: dict[str, Any],
) -> TurnProjectConfig:
    """Assemble the effective project config and workspace roots for the turn.

    Behavior-identical extraction of the inline block from
    ``prepare_agent_run``; ``session_metadata`` is read, never mutated.
    """

    user_project_ids = await get_user_project_ids(user_id, db)
    project_config = await _project_config_with_roles(db, user_id=user_id, project_id=project_id, user_roles=user_roles)
    app_workspace_root = resolve_app_workspace_root()
    session_workspace_root = Path(workspace_root).expanduser().resolve()
    tool_workspace_root = session_workspace_root
    project_workspace_root = app_workspace_root
    # A server phase turn of a run reads, writes and tests in the run's prepared working copy (its branch and base),
    # never the session's empty folder (a change phase without one is held at turn resolution).
    run_copy = await phase_working_copy(db, session_metadata)
    if run_copy is not None:
        # The base is recorded only for a copy that exists: a gone copy is never reported as verified.
        project_config = {
            **project_config, RUN_WORKING_COPY_KEY: str(run_copy[0]), RUN_BASE_SHA_KEY: run_copy[1] or None
        }
    engineering_tool_workspace_root = run_copy[0] if run_copy is not None else None
    if engineering_tool_workspace_root is None:
        engineering_tool_workspace_root = _resolved_engineering_tool_workspace_root(engineering_runtime_metadata)
    if engineering_tool_workspace_root is None:
        engineering_tool_workspace_root = _resolved_secure_work_tool_workspace_root(session_metadata)
    if engineering_tool_workspace_root is not None:
        tool_workspace_root = engineering_tool_workspace_root
        project_workspace_root = engineering_tool_workspace_root
        project_config = {
            **project_config,
            "resolved_repository_root": str(engineering_tool_workspace_root),
            "session_workspace_root": str(session_workspace_root),
        }
    project_config = {**project_config, "workspace_root": str(project_workspace_root)}
    project_config = _with_secure_work_repositories(project_config, session_metadata)
    project_config = _with_workspace_execution_view(project_config, session_metadata)
    if engineering_runtime_metadata:
        project_config = {
            **project_config,
            "engineering_knowledge_runtime_resolution": engineering_runtime_metadata,
        }
    return TurnProjectConfig(
        project_config=project_config,
        user_project_ids=user_project_ids,
        tool_workspace_root=tool_workspace_root,
    )


__all__ = [
    "TurnProjectConfig",
    "assemble_turn_project_config",
]
