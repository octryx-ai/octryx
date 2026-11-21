"""Repository source selection helpers shared by runtime tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _select_repository_readme_candidates(
    repo_path: Path,
    status_payload: dict[str, Any],
    *,
    workspace_root: Path,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    root_readme = repo_path / "README.md"
    if root_readme.exists():
        candidates.append((str(root_readme.relative_to(workspace_root)), "root_readme"))

    for entry in status_payload.get("top_level_directories") or []:
        if entry.get("readme_exists") and entry.get("readme_path"):
            candidates.append((str(entry["readme_path"]), "top_level_readme"))
            if len(candidates) >= 3:
                return candidates

    for entry in status_payload.get("modules") or []:
        if entry.get("readme_exists") and entry.get("readme_path"):
            candidates.append((str(entry["readme_path"]), "module_readme"))
            if len(candidates) >= 4:
                break
    return candidates


def _select_repository_code_candidates(
    repo_path: Path,
    analysis_payload: dict[str, Any],
    *,
    workspace_root: Path,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_candidate(path_value: str, reason: str) -> None:
        normalized = str(path_value).strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append((normalized, reason))

    for build_file in analysis_payload.get("build_files") or []:
        if build_file.get("path"):
            add_candidate(str(build_file["path"]), "build_file")
        if len(candidates) >= 4:
            return candidates

    for name in analysis_payload.get("top_level_files") or []:
        lowered = str(name).lower()
        if lowered in {"dockerfile", "chart.yaml", "values.yaml", "values.yml"} or lowered.endswith(
            (".ini", ".tf", ".yaml", ".yml", ".properties")
        ):
            add_candidate(str((repo_path / name).relative_to(workspace_root)), "top_level_config")
        if len(candidates) >= 4:
            return candidates

    interesting_names = {"dockerfile", "chart.yaml", "values.yaml", "values.yml"}
    interesting_suffixes = (".tf", ".ini", ".yaml", ".yml", ".properties")
    for candidate in repo_path.rglob("*"):
        if len(candidates) >= 4:
            break
        if not candidate.is_file():
            continue
        if any(part in {".git", "target", "node_modules", "dist", "build", ".venv"} for part in candidate.parts):
            continue
        lowered = candidate.name.lower()
        if lowered in interesting_names or lowered.endswith(interesting_suffixes):
            add_candidate(str(candidate.relative_to(workspace_root)), "config_or_infra")
    return candidates
