from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _workspace_media_type(path: Path) -> str:
    if path.is_dir():
        return "inode/directory"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _workspace_sort_key(root: Path, candidate: Path) -> tuple[int, int, str]:
    return (
        len(candidate.relative_to(root).parts),
        0 if candidate.is_dir() else 1,
        str(candidate.relative_to(root)).lower(),
    )


def _workspace_child_sort_key(candidate: Path) -> tuple[int, str]:
    return (0 if candidate.is_dir() else 1, candidate.name.lower())


def workspace_entry_for_path(workspace_root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(workspace_root)
    relative_path = str(relative)
    relative_parent = str(relative.parent)
    if relative_parent == ".":
        relative_parent = ""
    stat_result = path.stat()
    is_directory = path.is_dir()
    modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat()
    child_count = None
    if is_directory:
        try:
            child_count = sum(1 for _ in path.iterdir())
        except OSError:
            child_count = 0
    return {
        "path": str(path),
        "relativePath": relative_path,
        "parentPath": relative_parent,
        "name": path.name,
        "kind": "directory" if is_directory else "file",
        "depth": len(relative.parts) - 1,
        "mediaType": _workspace_media_type(path),
        "sizeBytes": None if is_directory else stat_result.st_size,
        "childCount": child_count,
        "url": "" if is_directory else "",
        "toolName": "",
        "createdAt": modified_at,
        "modifiedAt": modified_at,
    }


def serialize_workspace_children(workspace_root: Path, target: Path) -> list[dict[str, Any]]:
    root = workspace_root.resolve()
    if not root.exists():
        return []
    if not target.exists():
        return []
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    entries: list[dict[str, Any]] = []
    for path in sorted(target.iterdir(), key=_workspace_child_sort_key):
        entries.append(workspace_entry_for_path(root, path))
    return entries


def search_workspace_entries(
    workspace_root: Path,
    *,
    query: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    root = workspace_root.resolve()
    if not root.exists():
        return []
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return []
    normalized_limit = max(1, min(int(limit or 200), 500))
    matched_paths: list[Path] = []
    for path in root.rglob("*"):
        relative = str(path.relative_to(root))
        haystack = " ".join(
            [
                path.name,
                relative,
                "directory" if path.is_dir() else _workspace_media_type(path),
            ]
        ).lower()
        if normalized_query not in haystack:
            continue
        matched_paths.append(path)
        if len(matched_paths) >= normalized_limit:
            break

    included_paths: set[Path] = set()
    for path in matched_paths:
        current = path
        while current != root and current not in included_paths:
            included_paths.add(current)
            current = current.parent

    return [
        workspace_entry_for_path(root, path)
        for path in sorted(
            included_paths,
            key=lambda candidate: _workspace_sort_key(root, candidate),
        )
    ]
