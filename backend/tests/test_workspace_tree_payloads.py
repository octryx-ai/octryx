from __future__ import annotations

from pathlib import Path

from app.web._helpers.workspace_tree_payloads import (
    build_session_workspace_response,
    build_workspace_search_response,
    build_workspace_tree_response,
)


def test_build_session_workspace_response_adds_urls_only_for_files(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    entries = [
        {"kind": "directory", "name": "repo", "path": str(workspace_root / "repo")},
        {"kind": "file", "name": "notes.txt", "path": str(workspace_root / "notes.txt")},
    ]

    payload = build_session_workspace_response(
        workspace_root=workspace_root,
        entries=entries,
        changes=[{"id": "change-1"}],
    )

    assert payload["rootLabel"] == "workspace"
    assert payload["rootPath"] == str(workspace_root)
    assert payload["loadedDirectories"] == [""]
    assert "url" not in payload["files"][0]
    assert payload["files"][1]["url"].startswith("/chat/api/artifact?")
    assert payload["changes"] == [{"id": "change-1"}]


def test_build_workspace_tree_and_search_response_preserve_shape(tmp_path: Path) -> None:
    entries = [{"kind": "file", "name": "app.py", "path": str(tmp_path / "repo" / "app.py")}]

    tree_payload = build_workspace_tree_response(relative_path="repo", entries=entries)
    search_payload = build_workspace_search_response(query="app.py", entries=entries)

    assert tree_payload["path"] == "repo"
    assert list(tree_payload) == ["path", "files"]
    assert search_payload["query"] == "app.py"
    assert list(search_payload) == ["query", "files"]
    assert tree_payload["files"][0]["url"] == search_payload["files"][0]["url"]
