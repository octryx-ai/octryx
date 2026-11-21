from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

_WORKSPACE_AGENT_ROOTS = (
    Path(".agents"),
    Path(".octryx") / "agents",
)
_REPO_AGENT_ROOTS = (
    Path(".agents"),
    Path(".octryx") / "agents",
)
_DISCOVERY_CACHE_TTL_SECONDS = 15.0
_DISCOVERY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]
        return parts
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---\n"):
        return {}, text.strip()
    closing_index = stripped.find("\n---\n", 4)
    if closing_index == -1:
        return {}, text.strip()
    raw_meta = stripped[4:closing_index]
    body = stripped[closing_index + 5 :].strip()
    try:
        parsed = yaml.safe_load(raw_meta) or {}
    except Exception:
        parsed = {}
    return (parsed if isinstance(parsed, dict) else {}), body


def _discover_workspace_agent_paths(workspace_root: Path) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for relative_root in _WORKSPACE_AGENT_ROOTS:
        base = workspace_root / relative_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(base).parts
            if "knowledge" in relative_parts:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            discovered.append(path)
    return discovered


def _discover_repo_agent_paths(workspace_root: Path, project_config: dict[str, Any] | None) -> list[tuple[str, Path]]:
    config = dict(project_config or {})
    managed_repo_root = str(config.get("managed_repo_root") or "var/repos/bitbucket").strip()
    if not managed_repo_root:
        return []
    base_root = (workspace_root / managed_repo_root).resolve()
    paths: list[tuple[str, Path]] = []
    for item in config.get("bitbucket_allowed_repos") or []:
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        project_key = str(item.get("project_key") or "").strip()
        repo_slug = str(item.get("repo_slug") or "").strip()
        if not project_key or not repo_slug:
            continue
        repo_label = f"{project_key}/{repo_slug}"
        repo_root = base_root / project_key / repo_slug
        seen_repo_paths: set[Path] = set()
        for relative_root in _REPO_AGENT_ROOTS:
            agent_root = repo_root / relative_root
            if not agent_root.exists():
                continue
            for path in sorted(agent_root.rglob("*.md")):
                if not path.is_file():
                    continue
                relative_parts = path.relative_to(agent_root).parts
                if "knowledge" in relative_parts:
                    continue
                resolved = path.resolve()
                if resolved in seen_repo_paths:
                    continue
                seen_repo_paths.add(resolved)
                paths.append((repo_label, path))
    return paths


def _serialize_microagent(
    *,
    source_path: Path,
    workspace_root: Path,
    source_kind: str,
    repo_label: str | None,
) -> dict[str, Any] | None:
    try:
        raw_text = source_path.read_text(encoding="utf-8")
    except OSError:
        return None

    metadata, body = _parse_frontmatter(raw_text)
    instructions = body.strip()
    if not instructions:
        return None

    capabilities = [item.lower() for item in _normalize_string_list(metadata.get("capabilities"))]
    triggers = [item.lower() for item in _normalize_string_list(metadata.get("triggers") or metadata.get("keywords"))]
    repo_scope = _normalize_string_list(
        metadata.get("repo_scope") or metadata.get("repos") or metadata.get("repositories")
    )

    return {
        "name": str(metadata.get("name") or source_path.stem.replace("-", " ").title()).strip(),
        "description": str(metadata.get("description") or "").strip(),
        "instructions": instructions,
        "capabilities": capabilities,
        "triggers": triggers,
        "repo_scope": repo_scope,
        "always_include": bool(metadata.get("always_include", False)),
        "priority": int(metadata.get("priority") or 0),
        "source_kind": source_kind,
        "repo_label": repo_label,
        "source_path": str(source_path),
        "relative_path": str(source_path.resolve().relative_to(workspace_root.resolve())),
    }


def _build_discovery_cache_key(*, workspace_root: str, project_config: dict[str, Any] | None) -> str:
    normalized_config = json.dumps(project_config or {}, sort_keys=True, default=str)
    return f"{Path(str(workspace_root or '')).expanduser().resolve()}::{normalized_config}"


def discover_repo_microagents(
    *,
    workspace_root: str,
    project_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cache_key = _build_discovery_cache_key(workspace_root=workspace_root, project_config=project_config)
    now = time.monotonic()
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached and now - cached[0] <= _DISCOVERY_CACHE_TTL_SECONDS:
        return [dict(item) for item in cached[1]]

    root = Path(str(workspace_root or "")).expanduser().resolve()
    if not root.exists():
        return []

    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for path in _discover_workspace_agent_paths(root):
        serialized = _serialize_microagent(
            source_path=path,
            workspace_root=root,
            source_kind="workspace",
            repo_label=None,
        )
        if serialized is None or serialized["source_path"] in seen_paths:
            continue
        discovered.append(serialized)
        seen_paths.add(serialized["source_path"])

    for repo_label, path in _discover_repo_agent_paths(root, project_config):
        serialized = _serialize_microagent(
            source_path=path,
            workspace_root=root,
            source_kind="repository",
            repo_label=repo_label,
        )
        if serialized is None or serialized["source_path"] in seen_paths:
            continue
        discovered.append(serialized)
        seen_paths.add(serialized["source_path"])

    _DISCOVERY_CACHE[cache_key] = (now, [dict(item) for item in discovered])
    return discovered


def select_relevant_repo_microagents(
    *,
    microagents: list[dict[str, Any]],
    capability_type: str,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """The microagents a turn loads: explicit activation only, never prompt keywords.

    A microagent is active when its ``capabilities`` (if any) contain the turn's capability and
    its frontmatter declares ``always_include: true`` (repository-owned).
    ``triggers`` / ``keywords`` and ``repo_scope`` stay readable in the format but activate nothing:
    an entry written to apply to some wordings must not silently apply to every turn either. The
    order is deterministic (priority, Workspace before repository, name, path) and ``limit`` bounds
    the count.
    """
    selected: list[tuple[int, dict[str, Any]]] = []
    for microagent in microagents:
        capabilities = [str(item).strip().lower() for item in microagent.get("capabilities") or []]
        if capabilities and capability_type.lower() not in capabilities:
            continue
        if not bool(microagent.get("always_include")):
            continue
        score = int(microagent.get("priority") or 0)
        if microagent.get("source_kind") == "workspace":
            score += 5
        selected.append((score, microagent))

    selected.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("name") or "").lower(),
            str(item[1].get("relative_path") or "").lower(),
        )
    )
    return [item for _score, item in selected[: max(1, limit)]]
