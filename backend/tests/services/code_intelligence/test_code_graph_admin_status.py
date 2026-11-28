from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import CodeGraphFile, CodeGraphRun, Project
from app.services.code_intelligence.graph_admin import get_code_graph_admin_status
from app.services.code_intelligence.indexing import (
    run_code_index,
)
from app.services.code_intelligence.repository import (
    create_code_repository,
    list_code_repositories,
)


def _write_graph_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "def helper() -> str:\n"
        "    return 'ok'\n\n"
        "@app.get('/health')\n"
        "def health() -> str:\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (root / "src" / "worker.py").write_text(
        "from app import helper\n\n"
        "def run() -> str:\n"
        "    return helper()\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_code_graph_admin_status_reports_health_stale_errors_and_metrics(
    client,
    auth_headers,
    db,
    tmp_path: Path,
):
    repo_root = tmp_path / "repo"
    _write_graph_repo(repo_root)
    project = Project(
        id=str(uuid.uuid4()),
        name="graph-admin-project",
        description="Code graph admin status",
        is_active=True,
        config={},
    )
    db.add(project)
    await db.commit()
    created = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "graph-admin-repo",
            "repo_root": str(repo_root),
            "provider": "local",
            "graph_backend": "code_graph",
            "is_active": True,
        },
    )
    await run_code_index(db, repository_id=created["id"], force=True, trigger="test")

    status = await get_code_graph_admin_status(db, repository_id=created["id"], project_id=project.id)
    assert status["status"] == "ready"
    assert status["summary"]["file_count"] >= 2
    assert status["summary"]["node_count"] > 0
    assert status["latest_run"]["status"] == "ready"
    assert status["run_history"]
    assert status["metrics"]["latest_duration_ms"] is not None

    repositories = await list_code_repositories(db, project_id=project.id)
    assert repositories[0]["code_graph_status"]["status"] == "ready"

    run = (
        await db.execute(
            select(CodeGraphRun)
            .where(CodeGraphRun.code_repository_id == created["id"])
            .order_by(CodeGraphRun.started_at.desc())
        )
    ).scalar_one()
    graph_file = (
        await db.execute(
            select(CodeGraphFile).where(
                CodeGraphFile.run_id == run.id,
                CodeGraphFile.file_path == "src/app.py",
            )
        )
    ).scalar_one()
    graph_file.parse_error = "manual parse failure"
    await db.commit()
    (repo_root / "src" / "app.py").write_text(
        "def helper() -> str:\n"
        "    return 'changed'\n",
        encoding="utf-8",
    )

    stale_status = await get_code_graph_admin_status(db, repository_id=created["id"])
    assert stale_status["status"] == "stale"
    assert stale_status["stale_files"][0]["file_path"] == "src/app.py"
    assert stale_status["parse_errors"][0]["parse_error"] == "manual parse failure"

    endpoint = f"/admin/chat/api/panel/code-repositories/{created['id']}/code-graph?project_id={project.id}"
    response = await client.get(endpoint, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "stale"

    metrics_response = await client.get("/metrics", headers=auth_headers)
    assert metrics_response.status_code == 200
    # Counted where the index run finished, not counted from the tables per scrape.
    assert "octryx_code_graph_index_runs_total{" in metrics_response.text
