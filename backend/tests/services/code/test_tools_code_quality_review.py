"""Codebase pattern analysis, self-review, pull request descriptions and the code quality and git tools run via the registry."""

import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.code_quality_service import analyze_codebase_patterns
from app.services.review import build_pull_request_description, self_review_workspace_diff
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.services.code.tools_code_quality_support import _server_pipeline  # noqa: F401


def test_analyze_codebase_patterns_extracts_python_conventions(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "service.py").write_text(
        "from .util import helper\n"
        "from fastapi import HTTPException\n"
        "from fastapi.responses import JSONResponse\n"
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def handle_error_case():\n"
        "    logger.info('x')\n"
        "    raise HTTPException(status_code=400, detail='bad')\n"
        "    return JSONResponse({'ok': False})\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_service.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = analyze_codebase_patterns(cwd=repo)

    assert result["naming_convention"] == "snake_case"
    assert result["import_style"] == "mixed"
    assert result["error_handling_patterns"]["raise_http_exception"] >= 1
    assert result["test_patterns"]["sampled_test_files"] >= 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_self_review_and_pr_description_on_real_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text("def handle_refresh():\n    return True\n", encoding="utf-8")
    (repo / "tests.py").write_text("def test_refresh():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: initial PROJ-510"], cwd=repo, check=True, capture_output=True)

    (repo / "service.py").write_text(
        ("def handle_refresh():\n    print('debug')\n    api_key = '1234" + "567890secret'\n    return True\n"),
        encoding="utf-8",
    )
    (repo / "scratch.py").write_text(
        "TODO = 'follow up'\npassword = 'super-secret-value'\n",
        encoding="utf-8",
    )

    review = await self_review_workspace_diff(cwd=repo)
    pr_description = await build_pull_request_description(
        cwd=repo,
        summary="Harden refresh flow",
        template={
            "sections": ["summary", "changes", "test_plan", "risk", "checklist"],
            "checklist": ["Tests written and passing"],
        },
    )

    assert review["ready_for_pr"] is False
    assert any(item["type"] == "hardcoded_secret" for item in review["findings"])
    assert any(item["type"] == "todo_marker" for item in review["findings"])
    assert "scratch.py" in review["changed_files"]
    assert "## Summary" in pr_description["markdown"]
    assert "## Checklist" in pr_description["markdown"]
    assert "Tests written and passing" in pr_description["markdown"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_new_code_quality_and_git_tools_execute_via_registry(monkeypatch):
    ctx = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        db=None,
        workspace_root="/tmp",
    )

    async def fake_run_test_suite(**kwargs):
        return {"framework": "pytest", "all_green": True}

    async def fake_lint_and_format_workspace(**kwargs):
        return {"all_clean": True, "checks": []}

    async def fake_git_file_intelligence(**kwargs):
        return {"file": "service.py"}

    async def fake_git_coupling_map(**kwargs):
        return {"anchor_files": ["service.py"]}

    async def fake_git_function_blame(**kwargs):
        return {"symbol": "handle_refresh"}

    async def fake_git_conflict_predictor(**kwargs):
        return {"risk": "medium"}

    async def fake_git_knowledge_extract(**kwargs):
        return {"category": "codebase_history", "key": "repo_history", "value": {"decisions": []}, "persisted": False}

    async def fake_git_pr_context(**kwargs):
        return {"changed_files": ["service.py"]}

    async def fake_self_review_workspace_diff(**kwargs):
        return {"ready_for_pr": True, "findings": []}

    async def fake_build_pull_request_description(**kwargs):
        return {"markdown": "## Summary\nok"}

    monkeypatch.setattr("app.services.code_quality_service.run_test_suite", fake_run_test_suite)
    monkeypatch.setattr("app.services.code_quality_service.lint_and_format_workspace", fake_lint_and_format_workspace)
    monkeypatch.setattr(
        "app.services.code_quality_service.analyze_codebase_patterns", lambda **kwargs: {"naming_convention": "snake_case"}
    )
    monkeypatch.setattr("app.services.git_intelligence_service.git_file_intelligence", fake_git_file_intelligence)
    monkeypatch.setattr("app.services.git_intelligence_service.git_coupling_map", fake_git_coupling_map)
    monkeypatch.setattr("app.services.git_intelligence_service.git_function_blame", fake_git_function_blame)
    monkeypatch.setattr("app.services.git_intelligence_service.git_conflict_predictor", fake_git_conflict_predictor)
    monkeypatch.setattr("app.services.git_intelligence_service.git_knowledge_extract", fake_git_knowledge_extract)
    monkeypatch.setattr("app.services.git_intelligence_service.git_pr_context", fake_git_pr_context)
    monkeypatch.setattr("app.services.review.service.self_review_workspace_diff", fake_self_review_workspace_diff)
    monkeypatch.setattr("app.services.review.service.build_pull_request_description", fake_build_pull_request_description)

    test_result = await execute_tool("run_test_suite", {}, ctx)
    lint_result = await execute_tool("lint_and_format_workspace", {}, ctx)
    pattern_result = await execute_tool("analyze_codebase_patterns", {}, ctx)
    file_result = await execute_tool("git_file_intelligence", {"file": "service.py"}, ctx)
    coupling_result = await execute_tool("git_coupling_map", {"changed_files": ["service.py"]}, ctx)
    blame_result = await execute_tool("git_function_blame", {"file": "service.py", "symbol": "handle_refresh"}, ctx)
    predictor_result = await execute_tool("git_conflict_predictor", {"planned_files": ["service.py"]}, ctx)
    pr_context_result = await execute_tool("git_pr_context", {"changed_files": ["service.py"]}, ctx)
    review_result = await execute_tool("self_review_workspace_diff", {}, ctx)
    pr_description_result = await execute_tool("build_pull_request_description", {}, ctx)
    knowledge_result = await execute_tool("git_knowledge_extract", {}, ctx)

    assert test_result["all_green"] is True
    assert test_result["execution_event"]["kind"] == "test"
    assert test_result["execution_event"]["status"] == "succeeded"
    assert test_result["execution_event"]["tool_name"] == "run_test_suite"
    assert lint_result["all_clean"] is True
    assert pattern_result["naming_convention"] == "snake_case"
    assert file_result["file"] == "service.py"
    assert coupling_result["anchor_files"] == ["service.py"]
    assert blame_result["symbol"] == "handle_refresh"
    assert predictor_result["risk"] == "medium"
    assert pr_context_result["changed_files"] == ["service.py"]
    assert review_result["ready_for_pr"] is True
    assert "## Summary" in pr_description_result["markdown"]
    assert knowledge_result["key"] == "repo_history"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_build_pull_request_description_uses_seeded_template_via_tool(db, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True, capture_output=True)
    (repo / "service.py").write_text("print('x')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: bootstrap PROJ-777"], cwd=repo, check=True, capture_output=True)
    (repo / "service.py").write_text("print('y')\n", encoding="utf-8")

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
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
        "build_pull_request_description",
        {"cwd": str(repo), "project_id": project.id, "summary": "Refresh improvement"},
        ctx,
    )

    assert "## Summary" in result["markdown"]
    assert "## Checklist" in result["markdown"]
    assert "No hardcoded secrets" in result["markdown"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_analyze_codebase_patterns_returns_patterns_without_storing_them(db, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.py").write_text("def handle_refresh_token():\n    return True\n", encoding="utf-8")
    project = Project(id=str(uuid.uuid4()), name=f"patterns-{uuid.uuid4()}", is_active=True)
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
        "analyze_codebase_patterns",
        {"cwd": str(repo), "project_id": project.id, "persist": True},
        ctx,
    )

    # The KnowledgeMap the conventions were persisted into is retired.
    assert result["persisted"] is False
    assert result["naming_convention"]
