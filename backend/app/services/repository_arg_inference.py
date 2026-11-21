"""Repository tool argument inference helpers.

Service-owned module: infers Bitbucket workspace paths and default arguments
for repository tools.
"""

import importlib
from pathlib import Path

from ..tools.tool_names import ToolName

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def _workspace_root() -> Path:
    try:
        engine_module = importlib.import_module("app.agent.engine")
        candidate = getattr(engine_module, "WORKSPACE_ROOT", None)
        if isinstance(candidate, Path):
            return candidate.resolve()
    except (ImportError, AttributeError, TypeError, ValueError, OSError):
        pass
    return WORKSPACE_ROOT.resolve()


def _infer_repo_tool_args(tool_name: str, tool_args: dict, latest_repo_state: dict[str, str]) -> dict:
    inferred_args = dict(tool_args or {})
    latest_repo_state = latest_repo_state or {}
    local_path = latest_repo_state.get("local_path", "")
    repo_readme_path = latest_repo_state.get("repo_readme_path", "")
    branch_name = latest_repo_state.get("branch_name", "")
    relative_repo_path = latest_repo_state.get("relative_path", "")
    repo_root = Path(local_path) if local_path else None
    repo_relative_root = Path(relative_repo_path) if relative_repo_path else None
    project_key = str(inferred_args.get("project_key") or "").strip()
    repo_slug = str(inferred_args.get("repo_slug") or "").strip()
    workspace_root = _workspace_root()

    if not repo_root and project_key and repo_slug:
        candidate_repo_root = workspace_root / "var" / "repos" / "bitbucket" / project_key / repo_slug
        if candidate_repo_root.exists() and candidate_repo_root.is_dir():
            repo_root = candidate_repo_root.resolve()
            local_path = str(repo_root)
            relative_repo_path = str(repo_root.relative_to(workspace_root))
            repo_relative_root = Path(relative_repo_path)
            repo_readme_candidate = repo_root / "README.md"
            if repo_readme_candidate.exists():
                repo_readme_path = str(repo_readme_candidate)

    def resolve_workspace_relative_path(raw_value: str) -> str | None:
        if not repo_root or not repo_relative_root:
            return None
        candidate = Path(raw_value).expanduser()
        try:
            candidate.relative_to(repo_relative_root)
        except ValueError:
            return None

        workspace_root = repo_root
        for _ in repo_relative_root.parts:
            workspace_root = workspace_root.parent
        return str((workspace_root / candidate).resolve())

    def rebase_repo_relative(arg_name: str, *, default_to_readme: bool = False) -> None:
        if not repo_root:
            return
        raw_value = str(inferred_args.get(arg_name) or "").strip()
        if not raw_value:
            if default_to_readme and repo_readme_path:
                inferred_args[arg_name] = repo_readme_path
            return
        candidate = Path(raw_value).expanduser()
        if candidate.is_absolute():
            return
        if repo_relative_root and candidate.parts and candidate.parts[0] == repo_relative_root.parts[0]:
            inferred_args[arg_name] = str((workspace_root / candidate).resolve())
            return
        workspace_relative = resolve_workspace_relative_path(raw_value)
        if workspace_relative:
            inferred_args[arg_name] = workspace_relative
            return
        inferred_args[arg_name] = str((repo_root / candidate).resolve())

    if (
        tool_name in {"analyze_workspace_repository", "list_repository_readme_status", "generate_repository_readmes"}
        and not inferred_args.get("path")
        and local_path
    ):
        inferred_args["path"] = local_path
    elif tool_name in {"analyze_workspace_repository", "list_repository_readme_status", "generate_repository_readmes"}:
        rebase_repo_relative("path")
    elif tool_name == ToolName.LIST_WORKSPACE_DIRECTORY:
        if not inferred_args.get("path") and local_path:
            inferred_args["path"] = local_path
        rebase_repo_relative("path")
    elif tool_name == ToolName.READ_WORKSPACE_FILE:
        rebase_repo_relative("path")
        rebase_repo_relative("file_path")
    elif tool_name == ToolName.WRITE_WORKSPACE_FILE:
        rebase_repo_relative("path", default_to_readme=True)
        rebase_repo_relative("file_path", default_to_readme=True)
    elif tool_name == ToolName.COMMIT_AND_PUSH_REPOSITORY_BRANCH:
        if not inferred_args.get("local_path") and local_path:
            inferred_args["local_path"] = local_path
        if not inferred_args.get("branch_name") and branch_name:
            inferred_args["branch_name"] = branch_name

    return inferred_args
