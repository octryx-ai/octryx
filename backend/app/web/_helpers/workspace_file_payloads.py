"""Workspace file payload shaping helpers."""

from __future__ import annotations

from pathlib import Path

from .serialization import _serialize_timestamp

__all__ = [
    "_build_workspace_file_payload",
]


def _relative_workspace_file_parts(path: Path, workspace_root: Path | None) -> tuple[str, str, int]:
    if workspace_root is not None:
        try:
            relative_path = str(path.relative_to(workspace_root.resolve()))
        except ValueError:
            relative_path = path.name
    else:
        relative_path = path.name
    parent_path = str(Path(relative_path).parent)
    if parent_path == ".":
        parent_path = ""
    depth = len(Path(relative_path).parts) - 1
    return relative_path, parent_path, depth


def _build_workspace_file_payload(
    *,
    artifact: dict,
    tool_name: str,
    created_at,
    workspace_root: Path | None = None,
) -> dict:
    path = str(artifact.get("path") or "").strip()
    resolved_path = Path(path).resolve()
    relative_path, parent_path, depth = _relative_workspace_file_parts(resolved_path, workspace_root)
    created_at_value = _serialize_timestamp(created_at)
    return {
        "path": path,
        "relativePath": relative_path,
        "parentPath": parent_path,
        "name": artifact.get("name") or resolved_path.name,
        "kind": "file",
        "depth": depth,
        "mediaType": artifact.get("mediaType") or "",
        "sizeBytes": artifact.get("sizeBytes") or 0,
        "url": artifact.get("url") or "",
        "toolName": tool_name or "",
        "createdAt": created_at_value,
        "modifiedAt": created_at_value,
    }
