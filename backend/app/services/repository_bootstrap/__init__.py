"""Repository bootstrap service package."""

from .helpers import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    DEFAULT_GITIGNORE_LINES,
    find_git_root,
    get_repository_bootstrap_config,
    has_explicit_repository_bootstrap_config,
    normalize_repository_bootstrap_config,
    safe_repo_name,
    target_repository_path,
    workspace_has_content,
)
from .local import initialize_local_repository, run_git
from .providers import (
    bitbucket_base_url,
    bitbucket_credentials,
    create_bitbucket_repository,
    create_github_repository,
    github_api_base,
    github_token,
)
from .service import ensure_workspace_repository

__all__ = [
    "DEFAULT_BRANCH",
    "DEFAULT_COMMIT_MESSAGE",
    "DEFAULT_GITIGNORE_LINES",
    "bitbucket_base_url",
    "bitbucket_credentials",
    "create_bitbucket_repository",
    "create_github_repository",
    "ensure_workspace_repository",
    "find_git_root",
    "get_repository_bootstrap_config",
    "github_api_base",
    "github_token",
    "has_explicit_repository_bootstrap_config",
    "initialize_local_repository",
    "normalize_repository_bootstrap_config",
    "run_git",
    "safe_repo_name",
    "target_repository_path",
    "workspace_has_content",
]
