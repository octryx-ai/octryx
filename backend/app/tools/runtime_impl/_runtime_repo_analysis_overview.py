"""Repository structure analysis tools."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ...services.execution_runtime.server_env import with_git_hardening
from ._runtime_cli_helpers import _workspace_root
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_readme_helpers import _parse_build_file_metadata

_SKIP_DIR_NAMES = {".git", ".idea", "target", "node_modules", "dist", "build", ".gradle"}
_SOURCE_SUFFIXES = {".java", ".kt", ".kts", ".groovy", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}
_CONFIG_NAMES = {
    "application.properties",
    "application.yml",
    "application.yaml",
    "bootstrap.properties",
    "bootstrap.yml",
    "bootstrap.yaml",
    "logback.xml",
    "logback-spring.xml",
}
_CONFIG_SUFFIXES = {".properties", ".yml", ".yaml", ".toml", ".conf"}
_CI_NAMES = {
    "Jenkinsfile",
    "Dockerfile",
    "corpbuild.xml",
    "bitbucket-pipelines.yml",
    "bitbucket-pipelines.yaml",
    ".gitlab-ci.yml",
    ".gitlab-ci.yaml",
    "azure-pipelines.yml",
    "azure-pipelines.yaml",
}


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _reporting_root(repo_path: Path, workspace_root: Path) -> Path:
    if repo_path == workspace_root or workspace_root in repo_path.parents:
        return workspace_root
    return repo_path


def _is_skipped_repo_path(path: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def _limited_repo_files(repo_path: Path, reporting_root: Path, *, kind: str, limit: int) -> list[str]:
    files: list[str] = []
    for candidate in repo_path.rglob("*"):
        if len(files) >= limit:
            break
        if not candidate.is_file() or _is_skipped_repo_path(candidate):
            continue
        name = candidate.name
        lower_name = name.lower()
        suffix = candidate.suffix.lower()
        is_match = False
        if kind == "source":
            is_match = suffix in _SOURCE_SUFFIXES
        elif kind == "config":
            is_match = lower_name in _CONFIG_NAMES or suffix in _CONFIG_SUFFIXES
        elif kind == "ci":
            is_match = name in _CI_NAMES or ".github" in candidate.parts or "workflows" in candidate.parts
        elif kind == "readme":
            is_match = lower_name == "readme.md"
        if not is_match:
            continue
        files.append(_relative_to(candidate, reporting_root))
    return files


_BUILD_FILE_NAMES = (
    "pom.xml",
    "package.json",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
)
_BUILD_METADATA_KEYS = ("artifact_id", "group_id", "packaging", "package_name", "version")


def _top_level_entries(repo_path: Path) -> tuple[list[str], list[str]]:
    top_level_files: list[str] = []
    top_level_directories: list[str] = []
    for child in sorted(repo_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name in {".git", ".idea", ".DS_Store"}:
            continue
        if child.is_dir():
            top_level_directories.append(child.name)
        else:
            top_level_files.append(child.name)
    return top_level_files, top_level_directories


def _collect_build_files(repo_path: Path, reporting_root: Path, build_limit: int) -> list[dict[str, Any]]:
    build_files: list[dict[str, Any]] = []
    for candidate in repo_path.rglob("*"):
        if len(build_files) >= build_limit:
            break
        if not candidate.is_file():
            continue
        if _is_skipped_repo_path(candidate):
            continue
        if candidate.name not in _BUILD_FILE_NAMES:
            continue
        metadata = _parse_build_file_metadata(candidate)
        build_files.append(
            {
                "path": _relative_to(candidate, reporting_root),
                "relative_to_repo": str(candidate.relative_to(repo_path)),
                **metadata,
            }
        )
    return build_files


def _readme_heading(module_readme: Path) -> str:
    try:
        return next(
            (
                line.strip("# ").strip()
                for line in module_readme.read_text(encoding="utf-8").splitlines()
                if line.startswith("#")
            ),
            "",
        )
    except Exception:
        return ""


def _module_summaries(
    build_files: list[dict[str, Any]], repo_path: Path, reporting_root: Path, module_limit: int
) -> list[dict[str, Any]]:
    module_summaries: list[dict[str, Any]] = []
    for build_file in build_files:
        relative_to_repo = Path(build_file["relative_to_repo"])
        if relative_to_repo.name not in {"pom.xml", "package.json"}:
            continue
        module_dir = repo_path / relative_to_repo.parent
        if module_dir == repo_path:
            continue
        module_readme = module_dir / "README.md"
        summary: dict[str, Any] = {
            "path": _relative_to(module_dir, reporting_root),
            "relative_to_repo": str(module_dir.relative_to(repo_path)),
            "build_kind": build_file.get("kind"),
        }
        for key in _BUILD_METADATA_KEYS:
            if build_file.get(key):
                summary[key] = build_file[key]
        if module_readme.exists():
            summary["readme_heading"] = _readme_heading(module_readme)
        module_summaries.append(summary)
        if len(module_summaries) >= module_limit:
            break
    return module_summaries


def _current_branch(repo_path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_path), "branch", "--show-current"],
            env=with_git_hardening(os.environ),  # git runs nothing the working copy configures
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


class AnalyzeWorkspaceRepositoryTool:
    name = "analyze_workspace_repository"
    description = "Summarize a local repository's structure, build files, README coverage, and module hints."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        path_value = str(params.get("path") or params.get("local_path") or params.get("repo_path") or "").strip()
        if not path_value:
            return {"error": "path is required"}

        module_limit = max(1, min(int(params.get("module_limit") or 24), 60))
        build_limit = max(1, min(int(params.get("build_file_limit") or 40), 100))

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

        root = _workspace_root(context)
        reporting_root = _reporting_root(repo_path, root)
        top_level_files, top_level_directories = _top_level_entries(repo_path)
        build_files = _collect_build_files(repo_path, reporting_root, build_limit)

        readme_files = _limited_repo_files(repo_path, reporting_root, kind="readme", limit=build_limit)
        source_files = _limited_repo_files(repo_path, reporting_root, kind="source", limit=build_limit)
        config_files = _limited_repo_files(repo_path, reporting_root, kind="config", limit=build_limit)
        ci_files = _limited_repo_files(repo_path, reporting_root, kind="ci", limit=build_limit)

        module_summaries = _module_summaries(build_files, repo_path, reporting_root, module_limit)
        current_branch = _current_branch(repo_path)

        return {
            "path": str(repo_path),
            "relative_path": _relative_to(repo_path, reporting_root),
            "current_branch": current_branch,
            "top_level_files": top_level_files[:50],
            "top_level_directories": top_level_directories[:50],
            "build_files": build_files,
            "readme_files": readme_files,
            "source_files": source_files,
            "config_files": config_files,
            "ci_files": ci_files,
            "module_summaries": module_summaries,
            "module_count": len(module_summaries),
        }


__all__ = ["AnalyzeWorkspaceRepositoryTool"]
