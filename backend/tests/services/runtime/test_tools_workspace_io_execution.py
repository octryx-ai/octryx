"""Git diff execution events, saved Python script runtimes and output limits, and corrupt channel config handling."""

import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import (
    SavedPythonScript,
    SystemConfig,
)
from app.models.integration.channel_config import ChannelConfig
from app.services.channel_config import ChannelConfigService
from app.services.script import run_saved_script
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.support.tools_workspace_io_support import _init_git_repo, _server_pipeline  # noqa: F401


def _commit_all(path: Path, message: str = "baseline") -> None:
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", message], check=True, capture_output=True)


@pytest.mark.asyncio
async def test_get_git_diff_execution_event_success(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    tracked = repo / "main.tf"
    tracked.write_text("resource \"x\" \"old\" {}\n", encoding="utf-8")
    _commit_all(repo)
    tracked.write_text("resource \"x\" \"new\" {}\n", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(repo),
    )

    result = await execute_tool("get_git_diff", {}, context)

    assert result["exit_code"] == 0
    assert "resource \"x\" \"new\"" in result["diff"]
    event = result["execution_event"]
    assert event["kind"] == "diff"
    assert event["status"] == "succeeded"
    assert event["exit_code"] == 0
    assert event["cwd"] == str(repo)
    assert event["command"][:4] == ["git", "-C", str(repo), "diff"]
    assert event["stdout_chars"] >= len(result["diff"])


@pytest.mark.asyncio
async def test_get_git_diff_execution_event_failure(tmp_path):
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool("get_git_diff", {}, context)

    assert result["error"] == "git diff failed"
    assert result["exit_code"] != 0
    assert result["cwd"] == str(tmp_path)
    event = result["execution_event"]
    assert event["kind"] == "diff"
    assert event["status"] == "failed"
    assert event["exit_code"] == result["exit_code"]
    assert event["cwd"] == str(tmp_path)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_saved_python_script_rejects_unsupported_runtime(db):
    script = SavedPythonScript(
        id=str(uuid.uuid4()),
        name="unsafe",
        purpose="test",
        code="def main(args):\n    return 'ok'\n",
        runtime="bash",
        created_by_user_id="user-1",
    )
    db.add(script)
    await db.flush()

    result = await run_saved_script(db, script=script, args={}, workspace_root=str(Path.cwd()))

    assert "Saved script runtime must be one of" in result["error"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_saved_python_script_uses_system_output_limit(db, monkeypatch):
    async def fake_execute_with_runtime(**kwargs):
        return SimpleNamespace(
            timed_out=False,
            exit_code=0,
            stdout="x" * 200,
            stderr="",
            metadata={"provider": "docker", "containerized": True},
        )

    script = SavedPythonScript(
        id=str(uuid.uuid4()),
        name="truncate",
        purpose="test",
        code="def main(args):\n    return 'x' * 200\n",
        runtime="python3",
        created_by_user_id="user-1",
    )
    db.add(script)
    db.add(
        SystemConfig(
            key="agent.saved_script_max_output_chars",
            value="50",
            description="test override",
        )
    )
    await db.commit()

    monkeypatch.setattr("app.services.script.service.shutil.which", lambda command: "/usr/bin/docker")
    monkeypatch.setattr("app.services.script.service.execute_with_runtime", fake_execute_with_runtime)
    result = await run_saved_script(db, script=script, args={}, workspace_root=str(Path.cwd()))

    assert len(result["stdout"]) <= 65
    assert result["stdout"].endswith("\n...[truncated]")


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_channel_config_service_handles_corrupt_json(db):
    config = ChannelConfig(
        plugin_id="slack",
        name="Broken config",
        project_id=None,
        enabled=True,
        config="{not-json",
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    payload = ChannelConfigService._to_response(config)

    assert payload.config == {}
