"""Running the test suite: runtime metadata, Maven projects, dependency and baseline blockers, failures and newly broken tests."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.code_quality.helpers import resolve_maven_command
from app.services.code_quality_service import run_test_suite
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_code_quality_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_test_suite_includes_execution_runtime_metadata(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text("[tool.octryx.code_quality]\n", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_execute_with_runtime(**kwargs):
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": "2 passed\nTOTAL 10 0 100%",
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "docker", "containerized": True},
            },
        )()

    monkeypatch.setattr("app.services.code_quality_service.execute_with_runtime", fake_execute_with_runtime)

    result = await run_test_suite(cwd=repo)

    assert result["all_green"] is True
    assert result["execution_runtime"]["provider"] == "docker"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_test_suite_supports_maven_java_projects(monkeypatch, tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")
    report_dir = repo / "target" / "surefire-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "TEST-demo.xml").write_text(
        '<testsuite tests="2" failures="0" errors="0" skipped="0"></testsuite>',
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        assert cwd == repo
        return {
            "command": command,
            "exit_code": 0,
            "stdout": "",
            "stderr": "Tests run: 2, Failures: 0, Errors: 0, Skipped: 0",
            "execution_runtime": {"provider": "host"},
        }

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await run_test_suite(cwd=repo)

    assert result["framework"] == "maven"
    assert result["all_green"] is True
    assert result["passed"] == 2
    assert result["command"] == ["mvn", "-q", "test"]


def test_resolve_maven_command_falls_back_to_mvn_for_crlf_wrapper(tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    wrapper = repo / "mvnw"
    wrapper.write_bytes(b"#!/bin/sh\r\necho mvnw\r\n")
    wrapper.chmod(0o755)

    command = resolve_maven_command(repo, which_fn=lambda name: f"/usr/bin/{name}" if name == "mvn" else None)

    assert command == ["mvn"]


@pytest.mark.asyncio
async def test_run_test_suite_reports_private_dependency_blocker(monkeypatch, tmp_path: Path):
    repo = tmp_path / "java-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pom.xml").write_text("<project />", encoding="utf-8")

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        return {
            "command": command,
            "exit_code": 1,
            "stdout": "",
            "stderr": (
                "Non-resolvable parent POM: Could not transfer artifact "
                "com.example:parent:pom:1.0 from internal"
            ),
        }

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await run_test_suite(
        cwd=repo,
        project_config={
            "engineering_knowledge_runtime_resolution": {
                "prompt_contract": {"stack_key": "java-spring"},
                "engineering_knowledge_pack": {
                    "toolchain_policy": {
                        "profiles": {
                            "java-spring": {
                                "validation_gates": [{"name": "baseline_tests", "command": "mvn test"}]
                            }
                        }
                    }
                },
            }
        },
    )

    assert result["all_green"] is False
    assert result["validation_gates"] == [{"name": "baseline_tests", "command": "mvn test", "required": True}]
    assert result["validation_blockers"][0]["code"] == "private_dependency_access_required"
    assert "repository credentials" in result["validation_blockers"][0]["question"]


@pytest.mark.asyncio
async def test_run_test_suite_reports_baseline_validation_blocker(monkeypatch, tmp_path: Path):
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".octryx-codequality.json").write_text(
        '{"language":"python","test_runner":"pytest","requires_baseline_green":true}',
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.code_quality_service._which", lambda command: f"/usr/bin/{command}")

    async def fake_run_exec(command, *, cwd, timeout_sec=120, db=None, project_config=None):
        return {"command": command, "exit_code": 1, "stdout": "1 failed", "stderr": ""}

    monkeypatch.setattr("app.services.code_quality_service._run_exec", fake_run_exec)

    result = await run_test_suite(cwd=repo)

    assert result["all_green"] is False
    assert result["validation_blockers"][0]["code"] == "baseline_validation_failed"
    assert "Baseline" in result["validation_blockers"][0]["message"]


@pytest.mark.asyncio
async def test_run_test_suite_tool_failure_returns_execution_event(monkeypatch, tmp_path: Path):
    ctx = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={},
        db=None,
        workspace_root=str(tmp_path),
    )

    async def fake_run_test_suite(**kwargs):
        return {
            "framework": "pytest",
            "repo_root": str(tmp_path),
            "path": ".",
            "command": ["python", "-m", "pytest", ".", "-q"],
            "exit_code": 1,
            "all_green": False,
            "stdout": "FAILED tests/test_demo.py::test_bad",
            "stderr": "",
            "failed_tests": ["tests/test_demo.py::test_bad"],
        }

    monkeypatch.setattr("app.services.code_quality_service.run_test_suite", fake_run_test_suite)

    result = await execute_tool("run_test_suite", {}, ctx)

    assert result["all_green"] is False
    event = result["execution_event"]
    assert event["kind"] == "test"
    assert event["status"] == "failed"
    assert event["exit_code"] == 1
    assert event["cwd"] == str(tmp_path)
    assert event["command"] == ["python", "-m", "pytest", ".", "-q"]
    assert event["metadata"]["failed_tests"] == ["tests/test_demo.py::test_bad"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_test_suite_tracks_newly_broken_tests_across_session(db, tmp_path: Path):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[tool.octryx.code_quality]\ntest_runner='pytest'\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n\ndef test_bad():\n    assert False\n",
        encoding="utf-8",
    )
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    await db.commit()

    ctx = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    first = await execute_tool("run_test_suite", {"cwd": str(repo)}, ctx)
    assert first["framework"] == "pytest"
    assert "tests/test_demo.py::test_bad" in first["failed_tests"]
    assert "tests/test_demo.py::test_bad" in first["newly_broken"]

    second = await execute_tool("run_test_suite", {"cwd": str(repo)}, ctx)
    assert second["newly_broken"] == []
