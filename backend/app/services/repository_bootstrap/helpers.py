from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_BRANCH = "main"
DEFAULT_COMMIT_MESSAGE = "chore: initialize repository"
DEFAULT_GITIGNORE_LINES = [
    ".DS_Store",
    ".idea/",
    ".vscode/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
    "node_modules/",
    "dist/",
    "build/",
    "target/",
]
SAFE_REPO_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_repo_name(value: str) -> str:
    cleaned = SAFE_REPO_NAME_RE.sub("-", str(value or "").strip().lower()).strip("-.")
    return cleaned or "workspace"


def normalize_repository_bootstrap_config(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = config if isinstance(config, dict) else {}
    enabled = bool(raw.get("enabled", True))
    return {
        "enabled": enabled,
        "provider": str(raw.get("provider") or "local").strip().lower() or "local",
        "auto_bootstrap_on_session_start": bool(raw.get("auto_bootstrap_on_session_start", False)),
        "workspace_subdir": str(raw.get("workspace_subdir") or "").strip(),
        "default_repo_name": str(raw.get("default_repo_name") or "").strip(),
        "default_branch": str(raw.get("default_branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH,
        "create_readme": bool(raw.get("create_readme", True)),
        "create_gitignore": bool(raw.get("create_gitignore", True)),
        "initial_commit": bool(raw.get("initial_commit", True)),
        "initial_commit_message": str(raw.get("initial_commit_message") or DEFAULT_COMMIT_MESSAGE).strip()
        or DEFAULT_COMMIT_MESSAGE,
        "remote_visibility": str(raw.get("remote_visibility") or "private").strip().lower() or "private",
        "github_owner": str(raw.get("github_owner") or "").strip(),
        "github_owner_type": str(raw.get("github_owner_type") or "org").strip().lower() or "org",
        "bitbucket_project_key": str(raw.get("bitbucket_project_key") or "").strip(),
    }


def get_repository_bootstrap_config(project_config: dict[str, Any] | None) -> dict[str, Any]:
    config = project_config if isinstance(project_config, dict) else {}
    raw = config.get("repository_bootstrap")
    return normalize_repository_bootstrap_config(raw if isinstance(raw, dict) else {})


def has_explicit_repository_bootstrap_config(project_config: dict[str, Any] | None) -> bool:
    config = project_config if isinstance(project_config, dict) else {}
    return isinstance(config.get("repository_bootstrap"), dict)


def find_git_root(start_path: Path) -> Path | None:
    resolved = start_path.resolve()
    for candidate in [resolved, *resolved.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def target_repository_path(workspace_root: Path, config: dict[str, Any]) -> Path:
    subdir = str(config.get("workspace_subdir") or "").strip()
    if subdir:
        return (workspace_root / subdir).resolve()
    return workspace_root.resolve()


def workspace_has_content(path: Path) -> bool:
    if not path.exists():
        return False
    return any(child.name != ".git" for child in path.iterdir())
