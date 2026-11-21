"""File outlines, effective backend status, SCIP planning and annotation parsing, and tree-sitter outlines."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

import app.services.code_intelligence.semantic_build as semantic_build
from app.models import Project, User
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
from app.services.code_intelligence.semantic_build import (
    _parse_scip_snapshot_annotations,
    _plan_scip_command,
)
from tests.code_intelligence_service_support import _write_repo_fixture


@pytest.mark.asyncio
async def test_get_file_outline_returns_python_structure(db, tmp_path: Path):
    (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
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


def test_plan_scip_command_never_runs_the_java_build_on_the_server(monkeypatch, tmp_path: Path):
    """``scip-java index`` runs the repository's Maven/Gradle build: not on the server."""
    repo_root = tmp_path / "java-workspace"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pom.xml").write_text("<project />", encoding="utf-8")

    monkeypatch.setattr(
        semantic_build,
        "_find_binary",
        lambda name: "/usr/local/bin/scip-java" if name == "scip-java" else None,
    )

    plan = _plan_scip_command(repository_id="repo-1", repo_root=repo_root, language="java")

    assert (plan["status"], plan["reason"]) == ("skipped", "server_build_not_allowed")
    assert "command" not in plan


def test_parse_scip_snapshot_annotations_extracts_definitions_and_references(tmp_path: Path):
    snapshot_root = tmp_path / "snapshot"
    target = snapshot_root / "src/main/java/example/Helper.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "package example;\n"
        "//      ^^^^^^^ reference semanticdb maven . . example/\n"
        "public class Helper {\n"
        "//           ^^^^^^ definition semanticdb maven maven/example/demo 1.0 example/Helper#\n"
        "//                  display_name Helper\n"
        "//                  signature_documentation java public class Helper\n"
        "//                  kind Class\n"
        '  public static String message() { return "hi"; }\n'
        "//              ^^^^^^ reference semanticdb maven jdk 21 java/lang/String#\n"
        "//                     ^^^^^^^ definition semanticdb maven maven/example/demo 1.0 example/Helper#message().\n"
        "//                             display_name message\n"
        "//                             signature_documentation java public static String message()\n"
        "//                             kind StaticMethod\n"
        "}\n",
        encoding="utf-8",
    )

    parsed = _parse_scip_snapshot_annotations(snapshot_root)

    helper_defs = parsed["definitions_by_name"]["helper"]
    method_defs = parsed["definitions_by_name"]["message"]
    assert helper_defs[0]["path"] == "src/main/java/example/Helper.java"
    assert helper_defs[0]["kind"] == "class"
    assert method_defs[0]["signature"] == "java public static String message()"
    refs = parsed["references_by_symbol"]["example/"]
    assert refs[0]["path"] == "src/main/java/example/Helper.java"


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
    """Regression: tree-sitter offsets are byte offsets; slicing the str with
    them corrupted every name after a multi-byte character (e.g. a copyright
    sign in the license header): 'StatusController' became 'atusController {'."""
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
