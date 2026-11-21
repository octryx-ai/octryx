from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.repository_bootstrap.helpers import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    find_git_root,
    get_repository_bootstrap_config,
    has_explicit_repository_bootstrap_config,
    safe_repo_name,
    target_repository_path,
)
from app.services.repository_bootstrap.local import initialize_local_repository
from app.services.repository_bootstrap.providers import (
    create_bitbucket_repository,
    create_github_repository,
)


async def ensure_workspace_repository(
    *,
    workspace_root: Path,
    project_config: dict[str, Any] | None,
    session_id: str | None = None,
    reason: str = "write",
    timeout_sec: int = 120,
) -> dict[str, Any]:
    workspace_root = workspace_root.resolve()
    existing_root = find_git_root(workspace_root)
    if existing_root and (
        existing_root == workspace_root
        or existing_root in workspace_root.parents
        or workspace_root in existing_root.parents
    ):
        return {
            "status": "existing",
            "provider": "existing",
            "repo_path": str(existing_root),
            "branch": None,
            "session_id": session_id,
        }

    explicit_config = has_explicit_repository_bootstrap_config(project_config)
    config = get_repository_bootstrap_config(project_config)
    if reason == "session_start" and (
        not explicit_config or not config.get("enabled") or not config.get("auto_bootstrap_on_session_start")
    ):
        return {"status": "skipped", "reason": "auto_bootstrap_disabled", "session_id": session_id}
    if reason == "write" and explicit_config and not config.get("enabled"):
        return {"status": "skipped", "reason": "repository_bootstrap_disabled", "session_id": session_id}

    provider = str(config.get("provider") or "local").strip().lower() or "local"
    repo_path = target_repository_path(workspace_root, config)
    repo_name = safe_repo_name(str(config.get("default_repo_name") or "workspace"))
    remote_info: dict[str, Any] | None = None
    if provider == "github":
        remote_info = await create_github_repository(
            project_config=project_config or {},
            config=config,
            repo_name=repo_name,
        )
    elif provider == "bitbucket":
        remote_info = await create_bitbucket_repository(
            project_config=project_config or {},
            config=config,
            repo_name=repo_name,
        )
    elif provider != "local":
        raise ValueError(f"Unsupported repository bootstrap provider: {provider}")

    # The sign-in's header for the initial push (environment only; never in the remote URL, argv or a file).
    remote_git_env = (remote_info or {}).pop("git_env", None)
    init_result = await initialize_local_repository(
        **({"remote_git_env": remote_git_env} if remote_git_env else {}),
        repo_path=repo_path,
        repo_name=repo_name,
        default_branch=str(config.get("default_branch") or DEFAULT_BRANCH),
        create_readme=bool(config.get("create_readme", True)),
        create_gitignore=bool(config.get("create_gitignore", True)),
        initial_commit=bool(config.get("initial_commit", True)),
        initial_commit_message=str(config.get("initial_commit_message") or DEFAULT_COMMIT_MESSAGE),
        remote_url=str((remote_info or {}).get("clone_url") or "").strip() or None,
        timeout_sec=timeout_sec,
    )
    if init_result.get("error"):
        return {"status": "error", "provider": provider, "repo_path": str(repo_path), **init_result}

    return {
        "status": "bootstrapped",
        "provider": provider,
        "repo_path": str(repo_path),
        "branch": str(config.get("default_branch") or DEFAULT_BRANCH),
        "repository_name": repo_name,
        "session_id": session_id,
        "remote": {
            "full_name": (remote_info or {}).get("full_name"),
            "html_url": (remote_info or {}).get("html_url"),
            "clone_url": (remote_info or {}).get("clone_url"),
        }
        if remote_info
        else None,
        **init_result,
    }

