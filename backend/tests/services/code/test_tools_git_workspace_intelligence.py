"""Git intelligence tools read file history, coupling, blame, conflicts, PR context and change summaries from a real repository, and knowledge extraction returns history without storing it."""

import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.models import (
    Project,
)
from app.services.git_intelligence_service import (
    git_change_summary,
    git_conflict_predictor,
    git_coupling_map,
    git_file_intelligence,
    git_function_blame,
    git_pr_context,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_git_file_intelligence_and_coupling_map_on_real_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text("print('v1')\n", encoding="utf-8")
    (repo / "test_service.py").write_text("def test_v1():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: initial service PROJ-100"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text("print('v2')\n", encoding="utf-8")
    (repo / "test_service.py").write_text("def test_v2():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix: service update PROJ-101"], cwd=repo, check=True, capture_output=True)

    intelligence = await git_file_intelligence(cwd=repo, file_path="service.py")
    coupling = await git_coupling_map(cwd=repo, changed_files=["service.py"], threshold=0.5)

    assert intelligence["stats"]["total_commits"] >= 2
    assert "PROJ-100" in intelligence["jira_tickets"] or "PROJ-101" in intelligence["jira_tickets"]
    assert any(item["file"] == "test_service.py" for item in intelligence["co_changed_files"])
    assert any(item["file"] == "test_service.py" for item in coupling["coupled_files"])


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_git_function_blame_conflict_predictor_and_pr_context_on_real_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text(
        "def handle_refresh():\n    return 'v1'\n",
        encoding="utf-8",
    )
    (repo / "tests.py").write_text("def test_refresh():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: add refresh handler PROJ-401"], cwd=repo, check=True, capture_output=True
    )

    (repo / "service.py").write_text(
        "def handle_refresh():\n    return 'v2'\n",
        encoding="utf-8",
    )
    (repo / "tests.py").write_text("def test_refresh():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix: refresh race PROJ-402"], cwd=repo, check=True, capture_output=True)

    blame = await git_function_blame(cwd=repo, file_path="service.py", symbol="handle_refresh")
    predictor = await git_conflict_predictor(
        cwd=repo,
        planned_files=["service.py"],
        open_pull_requests=[
            {
                "id": "PR-9",
                "title": "refresh cleanup",
                "author": "qa",
                "status": "OPEN",
                "files": ["service.py", "tests.py"],
            }
        ],
    )
    pr_context = await git_pr_context(
        cwd=repo,
        changed_files=["service.py", "tests.py"],
        pr={"id": "PR-9", "title": "refresh cleanup"},
    )

    assert blame["symbol"] == "handle_refresh"
    assert blame["primary_author"] == "Dev"
    assert "PROJ-401" in blame["jira_tickets"] or "PROJ-402" in blame["jira_tickets"]
    assert predictor["risk"] == "high"
    assert predictor["overlapping_pull_requests"][0]["id"] == "PR-9"
    assert pr_context["pull_request"]["id"] == "PR-9"
    assert pr_context["related_jira"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_git_change_summary_uses_execution_runtime_adapter(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    observed: dict[str, Any] = {}

    async def fake_execute_with_runtime(**kwargs):
        observed["command"] = kwargs["command"]
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": "COMMIT\x1fabc123\x1f2026-03-30T10:00:00+00:00\x1fDev\x1fdev@example.com\x1ffix: sample PROJ-1\nservice.py\n",
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "docker", "containerized": True},
            },
        )()

    monkeypatch.setattr("app.services.git_intelligence_service.execute_with_runtime", fake_execute_with_runtime)

    result = await git_change_summary(cwd=repo, paths=["service.py"], days=7)

    assert observed["command"][0] == "git"
    assert result["summary"]["total_commits"] == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_git_knowledge_extract_returns_history_without_storing_it(db, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text("print('v1')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fix: token refresh race PROJ-300"], cwd=repo, check=True, capture_output=True
    )

    project = Project(id=str(uuid.uuid4()), name=f"git-knowledge-{uuid.uuid4()}", is_active=True)
    db.add(project)
    await db.commit()

    ctx = ToolContext(
        user_id="u1",
        project_ids=[project.id],
        roles=["admin"],
        session_id="s1",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "git_knowledge_extract",
        {"cwd": str(repo), "project_id": project.id, "scope": "."},
        ctx,
    )

    # The KnowledgeMap the history was persisted into is retired.
    assert result["persisted"] is False
    assert result["category"] == "codebase_history"
    assert "known_bugs" in result["value"]
