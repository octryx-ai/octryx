"""Create a GitHub repository and optionally bootstrap it into the workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.repository_bootstrap import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    create_github_repository,
    initialize_local_repository,
)
from ..context import ToolContext
from .common import _string
from .github import _github_owner, _github_token


class CreateGitHubRepositoryTool:
    name = "create_github_repository"
    description = "Create a new GitHub repository and optionally bootstrap it into the current workspace."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        repo_name = _string(params.get("name") or params.get("repository_name"))
        if not repo_name:
            return {"error": "name is required"}
        owner = _string(params.get("owner") or _github_owner(context))
        owner_type = (
            _string(params.get("owner_type") or context.project_config.get("github_owner_type") or "org").lower()
            or "org"
        )
        visibility = _string(params.get("visibility") or "private").lower() or "private"
        token = await _github_token(context)
        remote = await create_github_repository(
            project_config={**context.project_config, "github_token": token},
            config={
                "github_owner": owner,
                "github_owner_type": owner_type,
                "remote_visibility": visibility,
            },
            repo_name=repo_name,
        )
        remote_git_env = remote.pop("git_env", None)  # the token's header for the initial push; never returned
        bootstrap: dict[str, Any] | None = None
        local_path = _string(params.get("local_path"))
        if local_path:
            repo_path = Path(local_path)
            if not repo_path.is_absolute():
                repo_path = Path(context.workspace_root or Path.cwd()) / repo_path
            repo_path = repo_path.resolve()
            workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
            if workspace_root not in repo_path.parents and repo_path != workspace_root:
                return {"error": f"local_path must stay inside workspace root: {workspace_root}"}
            bootstrap = await initialize_local_repository(
                repo_path=repo_path,
                repo_name=repo_name,
                default_branch=_string(params.get("default_branch") or DEFAULT_BRANCH) or DEFAULT_BRANCH,
                create_readme=bool(params.get("create_readme", True)),
                create_gitignore=bool(params.get("create_gitignore", True)),
                initial_commit=bool(params.get("initial_commit", True)),
                initial_commit_message=_string(params.get("initial_commit_message") or DEFAULT_COMMIT_MESSAGE)
                or DEFAULT_COMMIT_MESSAGE,
                remote_url=_string(remote.get("clone_url")) or None,
                timeout_sec=max(60, min(int(params.get("timeout_sec") or 300), 1800)),
                **({"remote_git_env": remote_git_env} if remote_git_env else {}),
            )
            if bootstrap.get("error"):
                return bootstrap
        return {
            "provider": "github",
            "repository": remote,
            "local_bootstrap": bootstrap,
        }
