from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CPP_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
NODE_MODULE_DIRS = {".git", "node_modules", ".venv", "dist", "build", "__pycache__", "target"}
OPENREWRITE_DEFAULT_MAVEN_PLUGIN_VERSION = "6.37.0"


def _find_repo_root(cwd: Path) -> Path:
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _repo_has_any(repo_root: Path, names: tuple[str, ...]) -> bool:
    return any((repo_root / name).exists() for name in names)


def _iter_repo_files(repo_root: Path, suffixes: set[str], *, max_files: int | None = None) -> list[Path]:
    matches: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        if any(part in NODE_MODULE_DIRS for part in path.parts):
            continue
        matches.append(path)
        if max_files is not None and len(matches) >= max_files:
            break
    return matches


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _deep_merge_dicts(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
