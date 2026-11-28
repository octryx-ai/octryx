"""Code intelligence capabilities, the repository read and operation policies, listing, indexing and symbol queries."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import CodeIndexRun, Project
from app.services.code_intelligence import storage_capabilities
from app.services.code_intelligence.indexing import run_code_index
from app.services.code_intelligence.queries import (
    build_impact_analysis,
    find_symbol_definition,
    find_symbol_references,
    search_repository_code,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
    get_code_repository,
    list_code_repositories,
)
from tests.services.code_intelligence.code_intelligence_service_support import _write_repo_fixture


def test_code_intelligence_capabilities_report_zoekt_index_and_search_separately(monkeypatch):
    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"zoekt-index", "zoekt-git-index"} else None

    monkeypatch.setattr(storage_capabilities.shutil, "which", fake_which)
    capabilities = storage_capabilities.detect_code_intelligence_capabilities()
    zoekt = capabilities["search"]["zoekt"]

    assert zoekt["available"] is True
    assert zoekt["index_available"] is True
    assert zoekt["search_available"] is False
    assert zoekt["web_available"] is False


@pytest.mark.asyncio
async def test_code_repository_read_policy_blocks_code_intelligence_queries(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-read-policy-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "auto",
            "semantic_backend": "auto",
            "structure_backend": "auto",
            "graph_backend": "disabled",
            "config_json": {
                "operation_policy": {
                    "read": False,
                    "index": True,
                }
            },
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await search_repository_code(
            db=db,
            repository_id=created["id"],
            cwd=repo_root,
            project_id=project.id,
            query="helper",
            limit=20,
        )

    assert exc_info.value.status_code == 403
    assert "read" in str(exc_info.value.detail)

    repo = await get_code_repository(db, created["id"])
    assert repo.last_index_status == "not_indexed"
    run_count = (
        await db.execute(select(CodeIndexRun).where(CodeIndexRun.repository_id == created["id"]))
    ).scalars().all()
    assert run_count == []


@pytest.mark.asyncio
async def test_code_repository_listing_handles_missing_snapshot_and_null_config(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-null-config-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "workspace"
    _write_repo_fixture(repo_root)
    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "auto",
            "semantic_backend": "auto",
            "structure_backend": "auto",
            "graph_backend": "code_graph",
        },
    )
    repo = await get_code_repository(db, created["id"])
    repo.config_json = None
    repo.capabilities_json = None
    repo.latest_index_summary = None
    repo.last_index_status = "ready"
    await db.commit()

    repositories = await list_code_repositories(db, project_id=project.id)

    assert repositories[0]["id"] == created["id"]
    assert repositories[0]["config_json"] == {}
    assert repositories[0]["backend_status"]["index"]["mode"] == "fallback"
    assert repositories[0]["code_graph_status"]["status"] == "not_indexed"


@pytest.mark.asyncio
async def test_code_repository_index_respects_project_operation_policy(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-policy-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "auto",
            "semantic_backend": "auto",
            "structure_backend": "auto",
            "graph_backend": "disabled",
            "config_json": {
                "operation_policy": {
                    "read": True,
                    "index": False,
                }
            },
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    assert exc_info.value.status_code == 403
    assert "index" in str(exc_info.value.detail)

    repo = await get_code_repository(db, created["id"])
    assert repo.last_index_status == "not_indexed"
    run_count = (
        await db.execute(select(CodeIndexRun).where(CodeIndexRun.repository_id == created["id"]))
    ).scalars().all()
    assert run_count == []


@pytest.mark.asyncio
async def test_code_repository_index_and_symbol_queries(db, tmp_path: Path, auth_user):
    project = Project(
        id=str(uuid.uuid4()),
        name="code-intel-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "workspace"
    _write_repo_fixture(repo_root)

    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "auto",
            "semantic_backend": "auto",
            "structure_backend": "auto",
            "graph_backend": "disabled",
        },
    )
    indexed = await run_code_index(db, repository_id=created["id"], force=True, trigger="test")
    assert indexed["repository"]["last_index_status"] == "ready"
    assert indexed["snapshot"]["file_count"] >= 3
    assert indexed["snapshot"]["symbol_count"] >= 4

    search_result = await search_repository_code(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        query="helper",
        limit=20,
    )
    assert search_result["total_symbol_matches"] >= 1
    assert any(item["path"] == "src/app.py" for item in search_result["text_matches"])

    definitions = await find_symbol_definition(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        symbol="helper",
    )
    assert any(item["path"] == "src/app.py" for item in definitions["definitions"])

    references = await find_symbol_references(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        symbol="helper",
        limit=20,
    )
    assert references["total_references"] >= 2
    assert any(item["path"] == "src/usage.py" for item in references["references"])

    impact = await build_impact_analysis(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
        symbol="helper",
        limit=20,
    )
    assert impact["risk"] in {"low", "medium", "high"}
    assert "src/app.py" in impact["suggested_review_files"]
