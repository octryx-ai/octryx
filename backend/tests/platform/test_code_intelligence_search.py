"""Repository code search over Zoekt with its fallback, and symbol definitions and references through LSP."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import app.services.code_intelligence.indexing as indexing
from app.services.code_intelligence.queries import (
    find_symbol_definition,
    find_symbol_references,
    search_repository_code,
)
from app.services.lsp import lsp_manager


@pytest.mark.asyncio
async def test_search_repository_code_uses_zoekt_when_index_is_ready(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "zoekt-repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("def helper():\n    return 'hello'\n", encoding="utf-8")
    index_dir = tmp_path / "zoekt-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    async def fake_get_repository_snapshot(**kwargs):
        return {
            "repository": {"id": "repo-1", "name": "zoekt-repo"},
            "snapshot": {
                "repo_root": str(repo_root),
                "symbols": [{"name": "helper", "kind": "function", "path": "src/app.py", "line": 1}],
                "engines": {"index_backend": "zoekt"},
                "artifacts": {"zoekt": {"status": "ready", "index_dir": str(index_dir)}},
            },
        }

    class FakeProc:
        returncode = 0

        async def communicate(self):
            payload = {
                "FileName": "src/app.py",
                "LineMatches": [
                    {
                        "LineNumber": 1,
                        "Line": "ZGVmIGhlbHBlcigpOg==",
                        "LineFragments": [{"LineOffset": 4}],
                    }
                ],
            }
            return (f"{json.dumps(payload)}\n".encode(), b"")

    async def fake_create_subprocess_exec(*command, **kwargs):
        return FakeProc()

    monkeypatch.setattr(indexing, "get_repository_snapshot", fake_get_repository_snapshot)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/zoekt" if name == "zoekt" else None
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await search_repository_code(
        db=None,
        repository_id="repo-1",
        cwd=repo_root,
        project_id=None,
        query="helper",
        limit=20,
    )

    assert result["search_backend"] == "zoekt"
    assert result["text_matches"][0]["path"] == "src/app.py"
    assert result["text_matches"][0]["line"] == 1
    assert result["text_matches"][0]["column"] == 5
    assert result["text_matches"][0]["preview"] == "def helper():"


@pytest.mark.asyncio
async def test_search_repository_code_falls_back_when_zoekt_search_errors(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "zoekt-fallback-repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("def helper():\n    return 'hello'\n", encoding="utf-8")
    index_dir = tmp_path / "zoekt-index"
    index_dir.mkdir(parents=True, exist_ok=True)

    async def fake_get_repository_snapshot(**kwargs):
        return {
            "repository": {"id": "repo-1", "name": "zoekt-repo"},
            "snapshot": {
                "repo_root": str(repo_root),
                "symbols": [],
                "engines": {"index_backend": "zoekt"},
                "artifacts": {"zoekt": {"status": "ready", "index_dir": str(index_dir)}},
            },
        }

    class FakeProc:
        returncode = 2

        async def communicate(self):
            return (b"", b"zoekt failed")

    async def fake_create_subprocess_exec(*command, **kwargs):
        return FakeProc()

    monkeypatch.setattr(indexing, "get_repository_snapshot", fake_get_repository_snapshot)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/zoekt" if name == "zoekt" else None
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await search_repository_code(
        db=None,
        repository_id="repo-1",
        cwd=repo_root,
        project_id=None,
        query="helper",
        limit=20,
    )

    assert result["search_backend"] == "manual"
    assert result["text_matches"][0]["path"] == "src/app.py"


@pytest.mark.asyncio
async def test_find_symbol_definition_merges_lsp_workspace_symbols(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "lsp-symbols-repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("def helper():\n    return 'hello'\n", encoding="utf-8")

    async def fake_get_repository_snapshot(**kwargs):
        return {
            "repository": {"id": "repo-1", "name": "lsp-repo"},
            "snapshot": {
                "repo_root": str(repo_root),
                "symbols": [],
                "engines": {"semantic_backend": "regex"},
            },
        }

    class FakeClient:
        async def workspace_symbols(self, query):
            return [{"name": "helper", "kind": 12, "path": str(repo_root / "src" / "app.py"), "line": 1, "col": 5}]

    async def fake_get_or_create(language, workspace_root, **kwargs):
        return FakeClient()

    monkeypatch.setattr(indexing, "get_repository_snapshot", fake_get_repository_snapshot)
    monkeypatch.setattr(lsp_manager, "get_or_create", fake_get_or_create)

    result = await find_symbol_definition(
        db=None,
        repository_id="repo-1",
        cwd=repo_root,
        project_id=None,
        symbol="helper",
    )

    assert result["definitions"][0]["backend"] == "lsp"
    assert result["definitions"][0]["path"] == "src/app.py"


@pytest.mark.asyncio
async def test_find_symbol_references_uses_lsp_when_available(tmp_path: Path, monkeypatch):
    repo_root = tmp_path / "lsp-refs-repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text("def helper():\n    return 'hello'\n", encoding="utf-8")
    (repo_root / "src" / "usage.py").write_text("from app import helper\nhelper()\n", encoding="utf-8")

    async def fake_get_repository_snapshot(**kwargs):
        return {
            "repository": {"id": "repo-1", "name": "lsp-repo"},
            "snapshot": {
                "repo_root": str(repo_root),
                "symbols": [{"name": "helper", "kind": "function", "path": "src/app.py", "line": 1, "column": 5}],
                "engines": {"semantic_backend": "regex", "index_backend": "ripgrep"},
            },
        }

    class FakeClient:
        async def find_references(self, path, line, col, include_declaration=True):
            return [
                {"path": str(repo_root / "src" / "app.py"), "line": 1, "col": 5},
                {"path": str(repo_root / "src" / "usage.py"), "line": 2, "col": 1},
            ]

    async def fake_get_or_create(language, workspace_root, **kwargs):
        return FakeClient()

    monkeypatch.setattr(indexing, "get_repository_snapshot", fake_get_repository_snapshot)
    monkeypatch.setattr(lsp_manager, "get_or_create", fake_get_or_create)

    result = await find_symbol_references(
        db=None,
        repository_id="repo-1",
        cwd=repo_root,
        project_id=None,
        symbol="helper",
        limit=20,
    )

    assert result["search_backend"] == "lsp+text"
    assert any(item["path"] == "src/usage.py" for item in result["references"])
