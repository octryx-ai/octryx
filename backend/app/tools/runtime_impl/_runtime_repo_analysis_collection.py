"""Repository README generation tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ._runtime_cli_helpers import _workspace_root
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_readme_helpers import _build_module_descriptor, _module_summarizer
from ._runtime_readme_rendering import _render_module_readme, _render_root_readme, _render_top_level_readme

# Directories that hold build output or vendored code, never modules to document.
_SKIPPED_DIR_NAMES = {".git", "target", "node_modules", "dist", "build"}


def _top_level_directories(repo_path: Path) -> list[Path]:
    return [
        child
        for child in sorted(repo_path.iterdir(), key=lambda item: item.name.lower())
        if child.is_dir()
        and child.name not in _SKIPPED_DIR_NAMES
        and not child.name.startswith(".")
    ]


def _discover_modules(repo_path: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for build_file in sorted(repo_path.rglob("*")):
        if not build_file.is_file() or build_file.name not in {"pom.xml", "package.json"}:
            continue
        if any(part in _SKIPPED_DIR_NAMES for part in build_file.parts):
            continue
        module_dir = build_file.parent
        if module_dir == repo_path:
            continue
        relative_path = str(module_dir.relative_to(repo_path))
        if relative_path in seen_paths:
            continue
        seen_paths.add(relative_path)
        modules.append(_build_module_descriptor(module_dir, repo_path))

    modules.sort(key=lambda item: item["path"])
    return modules


def _write_group_readmes(
    repo_path: Path, workspace_root: Path, modules: list[dict[str, Any]], top_level_directories: list[Path]
) -> list[str]:
    written_files: list[str] = []
    top_level_names = [directory.name for directory in top_level_directories]
    root_readme = repo_path / "README.md"
    root_readme.write_text(
        _render_root_readme(repo_path.name, modules, top_level_names), encoding="utf-8"
    )
    written_files.append(str(root_readme.relative_to(workspace_root)))

    grouped_modules: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        grouped_modules.setdefault(module["kind"], []).append(module)

    for directory in top_level_directories:
        group_modules = [module for module in grouped_modules.get(directory.name, [])]
        top_level_readme = directory / "README.md"
        top_level_readme.write_text(
            _render_top_level_readme(directory.name, group_modules), encoding="utf-8"
        )
        written_files.append(str(top_level_readme.relative_to(workspace_root)))
    return written_files


class GenerateRepositoryReadmesTool:
    name = "generate_repository_readmes"
    description = "Generate root, top-level, and missing module README files for a local repository from its structure and build files."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        path_value = str(params.get("path") or params.get("local_path") or params.get("repo_path") or "").strip()
        if not path_value:
            return {"error": "path is required"}

        try:
            repo_path = _resolve_cwd(context.workspace_root, path_value)
        except ValueError as exc:
            return {"error": str(exc)}

        if not repo_path.exists() or not repo_path.is_dir():
            return {"error": "path is not a repository directory"}

        workspace_root = _workspace_root(context)
        top_level_directories = _top_level_directories(repo_path)
        modules = _discover_modules(repo_path)
        written_files = _write_group_readmes(repo_path, workspace_root, modules, top_level_directories)

        generated_module_readmes: list[str] = []
        skipped_existing: list[str] = []
        for module in modules:
            readme_path = repo_path / module["path"] / "README.md"
            if readme_path.exists():
                skipped_existing.append(module["path"])
                continue
            readme_path.write_text(_render_module_readme(module), encoding="utf-8")
            generated_module_readmes.append(module["path"])
            written_files.append(str(readme_path.relative_to(workspace_root)))

        missing_after_write = []
        for module in modules:
            if not (repo_path / module["path"] / "README.md").exists():
                missing_after_write.append(module["path"])

        _module_summarizer(modules, missing_after_write)

        return {
            "path": str(repo_path),
            "relative_path": str(repo_path.relative_to(workspace_root)),
            "written_files": written_files,
            "generated_module_readmes": generated_module_readmes,
            "skipped_existing_module_readmes": skipped_existing,
            "missing_after_write": missing_after_write,
            "missing_after_write_count": len(missing_after_write),
        }


__all__ = ["GenerateRepositoryReadmesTool"]
