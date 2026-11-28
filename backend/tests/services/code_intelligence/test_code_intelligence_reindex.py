"""Repository change warnings before a reindex and incremental reindex audits."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import CodeGraphStaleness, Project
from app.services.code_intelligence.graph_path_queries import get_code_graph_files
from app.services.code_intelligence.graph_queries import get_code_graph_status
from app.services.code_intelligence.indexing import (
    run_code_index,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from tests.services.code_intelligence.code_intelligence_service_support import _write_repo_fixture


@pytest.mark.asyncio
async def test_native_code_graph_status_warns_when_repository_changes_before_reindex(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="native-code-graph-stale-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "stale-workspace"
    _write_repo_fixture(repo_root)
    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "stale-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "code_graph",
        },
    )
    await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    (repo_root / "src" / "app.py").write_text(
        (repo_root / "src" / "app.py").read_text(encoding="utf-8") + "\ndef local_change() -> str:\n    return 'changed'\n",
        encoding="utf-8",
    )

    status = await get_code_graph_status(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
    )

    assert status["status"] == "stale"
    assert status["graph"]["is_stale"] is True
    assert status["graph"]["sync"]["files_modified"] == 1
    assert status["staleness_warnings"][0]["path"] == "src/app.py"
    assert status["staleness_warnings"][0]["status"] == "modified"


@pytest.mark.asyncio
async def test_native_code_graph_incremental_reindex_audits_add_modify_delete(db, tmp_path: Path):
    project = Project(
        id=str(uuid.uuid4()),
        name="native-code-graph-incremental-project",
        description="test project",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()

    repo_root = tmp_path / "incremental-workspace"
    _write_repo_fixture(repo_root)
    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "incremental-workspace",
            "repo_root": str(repo_root),
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "code_graph",
        },
    )
    await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    (repo_root / "src" / "usage.py").unlink()
    (repo_root / "src" / "app.py").write_text(
        (repo_root / "src" / "app.py").read_text(encoding="utf-8") + "\ndef changed_helper() -> str:\n    return helper()\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "extra.py").write_text(
        "def extra() -> str:\n    return 'extra'\n",
        encoding="utf-8",
    )

    indexed = await run_code_index(db, repository_id=created["id"], force=False, trigger="test")

    assert indexed["status"] == "indexed"
    sync = indexed["snapshot"]["artifacts"]["code_graph"]["persistence"]["sync"]
    assert sync["indexing_mode"] == "incremental"
    assert sync["files_added"] == 1
    assert sync["files_modified"] == 1
    assert sync["files_deleted"] == 1
    assert sync["files_to_index"] == 2
    assert sync["deleted_paths"] == ["src/usage.py"]

    status = await get_code_graph_status(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
    )
    assert status["status"] == "fresh"
    assert status["latest_run"]["metadata"]["sync"]["files_deleted"] == 1

    files = await get_code_graph_files(
        db=db,
        repository_id=created["id"],
        cwd=repo_root,
        project_id=project.id,
    )
    paths = {item["path"] for item in files["files"]}
    assert "src/extra.py" in paths
    assert "src/usage.py" not in paths

    deleted_staleness = (
        await db.execute(
            select(CodeGraphStaleness).where(
                CodeGraphStaleness.file_path == "src/usage.py",
                CodeGraphStaleness.status == "deleted",
            )
        )
    ).scalar_one()
    assert deleted_staleness.reason == "file_deleted_since_previous_graph_run"

