"""File outlines, effective backend status and tree-sitter outlines."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models import Project
from app.services.code_intelligence.indexing import (
    run_code_index,
)
from app.services.code_intelligence.outline_java import _tree_sitter_java_outline
from app.services.code_intelligence.outline_queries import (
    get_file_outline,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
    list_code_repositories,
)
from tests.services.code_intelligence.code_intelligence_service_support import _write_repo_fixture


@pytest.mark.asyncio
async def test_get_file_outline_returns_python_structure(db, tmp_path: Path, auth_user):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-outline-project",
        description="outline project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "outline-workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "outline-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "tree-sitter",
            "graph_backend": "disabled",
        },
    )
    await run_code_index(db, repository_id=created["id"], force=True, trigger="test")
    outline = await get_file_outline(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        file_path="src/app.py",
    )
    assert outline["language"] == "python"
    assert len(outline["outline"]) >= 2
    assert any(item["name"] == "helper" for item in outline["outline"])
    assert any(item["kind"] in {"function", "class"} for item in outline["outline"])
    assert len(outline["chunks"]) >= 1


@pytest.mark.asyncio
async def test_list_code_repositories_exposes_effective_backend_status(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-status-project",
        description="status project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "status-workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "status-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "auto",
            "semantic_backend": "auto",
            "structure_backend": "auto",
            "graph_backend": "auto",
        },
    )
    await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    repositories = await list_code_repositories(db, project_id=project.id)
    repository = repositories[0]

    assert repository["effective_backends"]["index"] in {"zoekt", "ripgrep"}
    assert repository["backend_status"]["index"]["effective"] == repository["effective_backends"]["index"]
    assert "detail" in repository["backend_status"]["semantic"]
    assert repository["backend_status"]["structure"]["effective"] in {"tree-sitter", "regex"}






def test_tree_sitter_java_outline_extracts_java_symbols(tmp_path: Path):
    target = tmp_path / "Example.java"
    target.write_text(
        "package example;\n"
        "public class Example {\n"
        "  private final String name;\n"
        "  public Example(String name) { this.name = name; }\n"
        "  public String greet() { return name; }\n"
        "}\n",
        encoding="utf-8",
    )

    outline = _tree_sitter_java_outline(target, target.read_text(encoding="utf-8"))

    kinds = {(item["name"], item["kind"]) for item in outline}
    assert ("Example", "class") in kinds
    assert ("Example", "constructor") in kinds
    assert ("greet", "method") in kinds
    assert ("name", "field") in kinds


def test_tree_sitter_java_outline_survives_multibyte_characters(tmp_path: Path):
    target = tmp_path / "StatusController.java"
    target.write_text(
        "// © 2026 Example Corp — Zürich Büro\n"
        "package example;\n"
        "public class StatusController {\n"
        "  public String status() { return \"ok\"; }\n"
        "}\n",
        encoding="utf-8",
    )

    outline = _tree_sitter_java_outline(target, target.read_text(encoding="utf-8"))

    names = {item["name"] for item in outline if item["kind"] == "class"}
    assert names == {"StatusController"}
    methods = {item["name"] for item in outline if item["kind"] == "method"}
    assert "status" in methods


@pytest.mark.asyncio
async def test_tree_sitter_structure_index_is_reused_for_outline(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-structure-project",
        description="structure project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "structure-workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "structure-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "tree-sitter",
            "graph_backend": "disabled",
        },
    )
    indexed = await run_code_index(db, repository_id=created["id"], force=True, trigger="test")
    tree_artifact = (indexed["snapshot"].get("artifacts") or {}).get("tree_sitter") or {}
    assert tree_artifact.get("index_path")
    assert Path(str(tree_artifact["index_path"])).exists()

    outline = await get_file_outline(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        file_path="src/app.py",
    )

    assert outline["structure_backend"] in {"tree-sitter", "python_ast", "regex"}
    assert any(item["name"] == "helper" for item in outline["outline"])
