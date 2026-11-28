"""Tests for bash tool resolution, CLI command routing, workspace git commits, and kubectl."""

from typing import Any

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.support.tools_turn_execution_pipeline_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
async def test_bash_tool_resolves_unique_workspace_script(monkeypatch, tmp_path):
    repo_dir = tmp_path / "services" / "api"
    repo_dir.mkdir(parents=True)
    manage_py = repo_dir / "manage.py"
    manage_py.write_text("print('ok')\n", encoding="utf-8")

    captured: dict[str, Any] = {}

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"done", b"")

    async def fake_shell(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="test",
        project_config={},
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    assert result["returncode"] == 0
    assert result["effective_command"] == "python3 manage.py migrate"
    assert result["script_resolution"]["resolved_path"] == str(manage_py)
    assert result["cwd"] == str(repo_dir)
    assert captured["cwd"] == str(repo_dir)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_reports_missing_workspace_script_without_running(tmp_path, monkeypatch):
    called = {"value": False}

    async def fake_shell(*args, **kwargs):
        called["value"] = True
        raise AssertionError("subprocess should not run")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="test",
        project_config={},
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    assert "not found" in result["error"]
    assert result["script_resolution"]["script"] == "manage.py"
    assert result["script_resolution"]["candidate_count"] == 0
    assert called["value"] is False


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_prefers_allowed_repo_root_for_manage_py(monkeypatch, tmp_path):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-web"
    repo_root.mkdir(parents=True)
    manage_py = repo_root / "manage.py"
    manage_py.write_text("print('ok')\n", encoding="utf-8")

    captured: dict[str, Any] = {}

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"done", b"")

    async def fake_shell(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="test",
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "SHOP", "repo_slug": "acme-orders-web", "enabled": True}],
        },
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    assert result["returncode"] == 0
    assert result["cwd"] == str(repo_root)
    assert result["script_resolution"]["resolved_path"] == str(manage_py)
    assert captured["cwd"] == str(repo_root)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_cli_command_prefers_allowed_repo_with_package_json(monkeypatch, tmp_path):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "frontend"
    repo_root.mkdir(parents=True)
    (repo_root / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")

    captured: dict[str, Any] = {}

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"installed", b"")

    async def fake_exec(*command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="test",
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "SHOP", "repo_slug": "frontend", "enabled": True}],
        },
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("run_cli_command", {"command": "npm install"}, context)

    assert result["exit_code"] == 0
    assert result["cwd"] == str(repo_root)
    assert result["script_resolution"]["repo_resolution"]["resolved_repo_root"] == str(repo_root)
    assert captured["cwd"] == str(repo_root)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_prefers_single_allowed_repo_for_git_status(monkeypatch, tmp_path):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "service-config"
    repo_root.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    captured: dict[str, Any] = {}

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"clean", b"")

    async def fake_shell(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return DummyProcess()

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="test",
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "SHOP", "repo_slug": "service-config", "enabled": True}],
        },
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("bash", {"command": "git status"}, context)

    assert result["returncode"] == 0
    assert result["cwd"] == str(repo_root)
    assert result["script_resolution"]["repo_resolution"]["mode"] == "single_allowed_repo"
    assert captured["cwd"] == str(repo_root)
