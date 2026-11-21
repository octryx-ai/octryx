"""Workspace git commit listing, saved Python scripts and kubectl run through the tool registry."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models import User
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_turn_execution_pipeline_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_workspace_git_commits_tool(monkeypatch):
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (
                b"abc123\x1fabc123\x1fAlice Example\x1falice@example.com\x1f2026-03-20T10:00:00+00:00\x1fUpdate config\n",
                b"",
            )

    async def fake_exec(*args, **kwargs):
        assert args[0] == "git"
        assert any(str(arg).startswith("--since=") for arg in args)
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root="/srv/octryx",
    )
    result = await execute_tool("list_workspace_git_commits", {"days": 5, "limit": 10}, context)
    assert result["days"] == 5
    assert result["commit_count"] == 1
    assert result["commits"][0]["short_commit"] == "abc123"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_workspace_git_commits_ignores_model_limit_without_user_limit(monkeypatch):
    observed_args: list[tuple[Any, ...]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_exec(*args, **kwargs):
        observed_args.append(args)
        return FakeProcess()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        current_user_message="Erstelle eine Wochenzusammenfassung aus Jira, Bitbucket und Confluence.",
        project_config={},
        workspace_root="/srv/octryx",
    )

    await execute_tool("list_workspace_git_commits", {"days": 5, "limit": 25}, context)

    assert "--max-count=250" in observed_args[0]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_save_and_run_saved_python_script_tool(db, tmp_path, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["operator"],
        session_id="test",
        project_config={},
        db=db,
        workspace_root=str(tmp_path),
    )

    artifact_name = f"sum_values_{uuid.uuid4().hex}.png"

    save_result = await execute_tool(
        "save_python_script",
        {
            "name": "sum_values",
            "purpose": "Add two numbers",
            "description": "Reusable helper for simple arithmetic",
            "code": (
                "from pathlib import Path\n"
                f"ARTIFACT = {artifact_name!r}\n"
                "def main(args):\n"
                "    total = args.get('a', 0) + args.get('b', 0)\n"
                "    Path(ARTIFACT).write_bytes(b'fake-png-data')\n"
                "    return f'Chart saved as: {ARTIFACT}\\nTotal: {total}'\n"
            ),
        },
        context,
    )
    assert save_result["name"] == "sum_values"

    list_result = await execute_tool("list_saved_python_scripts", {}, context)
    assert any(script["name"] == "sum_values" for script in list_result["scripts"])

    async def fake_execute_with_runtime(**kwargs):
        command = kwargs["command"]
        assert command[0] == "python3"
        assert kwargs["project_config"]["execution_runtime_provider"] == "docker"
        assert kwargs["project_config"]["execution_runtime_sandbox_mode"] == "hard"
        (tmp_path / artifact_name).write_bytes(b"fake-png-data")
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": f"Chart saved as: {artifact_name}\nTotal: 7\n",
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "docker", "sandbox_mode": "hard"},
            },
        )()

    monkeypatch.setattr("app.services.script.service.execute_with_runtime", fake_execute_with_runtime)
    monkeypatch.setattr("app.services.script.service.shutil.which", lambda name: "/usr/bin/docker")

    run_result = await execute_tool(
        "run_saved_python_script",
        {"name": "sum_values", "args": {"a": 2, "b": 5}},
        context,
    )
    assert run_result["exit_code"] == 0, run_result
    assert run_result["parsed_output"] is None
    assert "Chart saved as:" in run_result["stdout"]
    assert len(run_result["artifacts"]) == 1
    assert run_result["artifacts"][0]["name"] == artifact_name

    get_result = await execute_tool("get_saved_python_script", {"name": "sum_values", "include_code": True}, context)
    assert get_result["name"] == "sum_values"
    assert "def main" in get_result["code"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_kubectl_tool(monkeypatch):
    async def fake_execute_with_runtime(**kwargs):
        assert kwargs["command"][0] == "/opt/homebrew/bin/kubectl"
        return type(
            "FakeRuntimeResult",
            (),
            {
                "exit_code": 0,
                "stdout": '{"clientVersion":{"gitVersion":"v1.30.0"}}',
                "stderr": "",
                "timed_out": False,
                "metadata": {"provider": "host", "containerized": False},
            },
        )()

    async def fake_resolve_runtime_config(db, *, project_config=None):
        return type(
            "FakeRuntimeConfig",
            (),
            {"provider": "host", "docker_image": "python:3.11-slim", "docker_network_mode": "none"},
        )()

    monkeypatch.setattr("app.services.execution_runtime.service.execute_with_runtime", fake_execute_with_runtime)
    monkeypatch.setattr("app.services.execution_runtime.config.resolve_execution_runtime_config", fake_resolve_runtime_config)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "kubectl_path": "/opt/homebrew/bin/kubectl",
            "kubeconfig_path": "~/.kube/config",
            "k8s_context": "demo",
        },
        workspace_root="/srv/octryx",
    )
    result = await execute_tool("run_kubectl", {"args": ["version", "--client=true", "-o", "json"]}, context)
    assert result["exit_code"] == 0
    assert "v1.30.0" in result["stdout"]
