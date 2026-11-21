"""Workspace route response payload helpers."""

from __future__ import annotations

from pathlib import Path

from .workspace_artifacts import _workspace_artifact_url

__all__ = [
    "build_session_workspace_response",
    "build_workspace_file_listing",
    "build_workspace_search_response",
    "build_workspace_tree_response",
]


def build_workspace_file_listing(entries: list[dict]) -> list[dict]:
    payload_entries: list[dict] = []
    for entry in entries:
        payload_entry = dict(entry)
        if payload_entry.get("kind") == "file":
            payload_entry["url"] = _workspace_artifact_url(str(payload_entry.get("path") or ""))
        payload_entries.append(payload_entry)
    return payload_entries


def build_session_workspace_response(
    *,
    workspace_root: Path,
    entries: list[dict],
    changes: list[dict],
) -> dict:
    return {
        "rootLabel": workspace_root.name,
        "rootPath": str(workspace_root),
        "isTemporary": True,
        "files": build_workspace_file_listing(entries),
        "loadedDirectories": [""],
        "changes": changes,
    }


def build_workspace_tree_response(*, relative_path: str, entries: list[dict]) -> dict:
    return {
        "path": str(relative_path or ""),
        "files": build_workspace_file_listing(entries),
    }


def build_workspace_search_response(*, query: str, entries: list[dict]) -> dict:
    return {
        "query": str(query or ""),
        "files": build_workspace_file_listing(entries),
    }
