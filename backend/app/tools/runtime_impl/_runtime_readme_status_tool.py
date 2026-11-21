"""The ``list_repository_readme_status`` tool: README coverage of top-level folders and module directories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ._runtime_cli_helpers import _workspace_root
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_readme_helpers import _parse_build_file_metadata
from ._runtime_repo_analysis_overview import _relative_to, _reporting_root

# Directories that hold build output or vendored code, never modules to document.
_SKIPPED_DIR_NAMES = {".git", "target", "node_modules", "dist", "build"}


def _top_level_readme_entries(repo_path: Path, reporting_root: Path, top_level_limit: int) -> list[dict[str, Any]]:
    top_level_directories: list[dict[str, Any]] = []
    for child in sorted(repo_path.iterdir(), key=lambda item: item.name.lower()):
        if (
            not child.is_dir()
            or child.name.startswith(".")
            or child.name in _SKIPPED_DIR_NAMES
        ):
            continue
        readme_path = child / "README.md"
        top_level_directories.append(
            {
                "name": child.name,
                "path": _relative_to(child, reporting_root),
                "readme_exists": readme_path.exists(),
                "readme_path": _relative_to(readme_path, reporting_root),
            }
        )
        if len(top_level_directories) >= top_level_limit:
            break
    return top_level_directories


def _module_readme_entry(candidate: Path, module_dir: Path, relative_module_dir: str,
                         reporting_root: Path) -> dict[str, Any]:
    metadata = _parse_build_file_metadata(candidate)
    readme_path = module_dir / "README.md"
    module_entry: dict[str, Any] = {
        "path": _relative_to(module_dir, reporting_root),
        "relative_to_repo": relative_module_dir,
        "build_file": _relative_to(candidate, reporting_root),
        "build_kind": metadata.get("kind"),
        "readme_exists": readme_path.exists(),
        "readme_path": _relative_to(readme_path, reporting_root),
    }
    for key in ("artifact_id", "group_id", "packaging", "package_name", "version"):
        if metadata.get(key):
            module_entry[key] = metadata[key]
    return module_entry


def _module_readme_entries(repo_path: Path, reporting_root: Path, module_limit: int) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    seen_dirs: set[str] = set()
    build_patterns = {"pom.xml", "package.json"}
    for candidate in repo_path.rglob("*"):
        if len(modules) >= module_limit:
            break
        if not candidate.is_file() or candidate.name not in build_patterns:
            continue
        if any(part in _SKIPPED_DIR_NAMES for part in candidate.parts):
            continue
        module_dir = candidate.parent
        if module_dir == repo_path:
            continue
        relative_module_dir = str(module_dir.relative_to(repo_path))
        if relative_module_dir in seen_dirs:
            continue
        seen_dirs.add(relative_module_dir)
        modules.append(_module_readme_entry(candidate, module_dir, relative_module_dir, reporting_root))
    return modules


class ListRepositoryReadmeStatusTool:
    name = "list_repository_readme_status"
    description = "List README coverage for repository top-level folders and module directories so missing documentation can be fixed."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        path_value = str(params.get("path") or params.get("local_path") or params.get("repo_path") or "").strip()
        if not path_value:
            return {"error": "path is required"}

        top_level_limit = max(1, min(int(params.get("top_level_limit") or 50), 100))
        module_limit = max(1, min(int(params.get("module_limit") or 200), 500))
        try:
            repo_path = _resolve_cwd(
                context.workspace_root,
                path_value,
                context=context,
                allow_repo_fallback=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if not repo_path.exists():
            return {"error": "path does not exist"}
        if not repo_path.is_dir():
            return {"error": "path is not a directory"}

        workspace_root = _workspace_root(context)
        reporting_root = _reporting_root(repo_path, workspace_root)

        top_level_directories = _top_level_readme_entries(repo_path, reporting_root, top_level_limit)
        modules = _module_readme_entries(repo_path, reporting_root, module_limit)

        missing_top_level = [entry for entry in top_level_directories if not entry["readme_exists"]]
        missing_modules = [entry for entry in modules if not entry["readme_exists"]]

        return {
            "path": str(repo_path),
            "relative_path": _relative_to(repo_path, reporting_root),
            "top_level_directories": top_level_directories,
            "missing_top_level_readmes": missing_top_level,
            "modules": modules,
            "missing_module_readmes": missing_modules,
            "missing_total": len(missing_top_level) + len(missing_modules),
        }


__all__ = ["ListRepositoryReadmeStatusTool"]
