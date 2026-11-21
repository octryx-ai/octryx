"""run_cli_command syncs workspace changes, guards dirty workspaces, records validation outcomes and rejects shell control operators."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.services.execution_runtime import ExecutionRuntimeResult
from app.services.system_config import set_system_config_value
from app.services.system_config.constants import (
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
)
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_workspace_io_support import _init_git_repo, _server_pipeline  # noqa: F401


@pytest.mark.asyncio
async def test_run_cli_command_syncs_workspace_changes_to_filesystem_storage(db, tmp_path):
    storage_root = tmp_path / "objects"
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/cli")
    await db.commit()

    from app.models import Session

    session = Session(id="cli-sync-session-1", user_id="user-1", metadata_={})
    db.add(session)
    await db.flush()

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id=session.id,
        project_config={},
        workspace_root=str(tmp_path / "workspace"),
        db=db,
    )
    write_result = await execute_tool("run_cli_command", {"command": "touch cli.txt"}, context)

    object_path = storage_root / "octryx" / "cli" / "sessions" / session.id / "workspace" / "current" / "cli.txt"
    assert write_result["exit_code"] == 0
    assert write_result["workspace_sync"]["status"] == "synced"
    assert write_result["workspace_change_contract"]["kind"] == "workspace_change_safety_contract"
    assert {"status": "??", "path": "cli.txt"} in write_result["workspace_change_contract"]["changed_files"]
    assert object_path.exists()

    delete_result = await execute_tool(
        "run_cli_command",
        {"command": "rm cli.txt", "allow_dirty_workspace": True},
        context,
    )

    assert delete_result["exit_code"] == 0
    assert delete_result["workspace_sync"]["status"] == "synced"
    assert not object_path.exists()


@pytest.mark.asyncio
async def test_run_cli_command_blocks_mutation_when_workspace_is_dirty(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    dirty = repo / "user.txt"
    dirty.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "user.txt"], check=True, capture_output=True)
    dirty.write_text("user change\n", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(repo),
    )
    result = await execute_tool("run_cli_command", {"command": "touch generated.txt"}, context)

    assert "Refusing to run a mutating command" in result["error"]
    assert not (repo / "generated.txt").exists()
    contract = result["workspace_change_contract"]
    assert contract["preexisting_dirty_paths"] == ["user.txt"]
    assert "workspace_dirty_before" in contract["risk_markers"]


@pytest.mark.asyncio
async def test_run_cli_command_validation_records_change_contract(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(repo),
    )
    command = f"{sys.executable} -m pytest --version"
    result = await execute_tool("run_cli_command", {"command": command}, context)

    assert result["exit_code"] == 0
    assert result["execution_event"]["kind"] == "validation"
    assert result["execution_event"]["status"] == "succeeded"
    assert result["execution_event"]["tool_name"] == "run_cli_command"
    assert result["execution_event"]["cwd"] == str(repo)
    contract = result["workspace_change_contract"]
    assert contract["kind"] == "workspace_change_safety_contract"
    assert contract["validation"]["command"] == command
    assert contract["validation"]["status"] == "passed"
    assert contract["dirty_before_count"] == 0
    assert contract["dirty_after_count"] == 0


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_cli_command_tool(tmp_path):
    workspace_root = str(tmp_path)
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=workspace_root,
    )
    result = await execute_tool("run_cli_command", {"command": "printf hello"}, context)
    assert result["exit_code"] == 0
    assert result["stdout"] == "hello"
    event = result["execution_event"]
    assert event["kind"] == "shell"
    assert event["status"] == "succeeded"
    assert event["exit_code"] == 0
    assert event["command"] == ["printf", "hello"]
    assert event["cwd"] == workspace_root
    assert event["stdout_chars"] == 5
    assert event["stderr_chars"] == 0


@pytest.mark.asyncio
async def test_run_cli_command_validation_outcome_missing_tool(monkeypatch, tmp_path):
    async def fake_execute_with_runtime(**kwargs):
        assert kwargs["command"] == ["terraform", "validate"]
        return ExecutionRuntimeResult(
            exit_code=127,
            stdout="",
            stderr="terraform: command not found",
            timed_out=False,
            metadata={"provider": "host"},
        )

    monkeypatch.setattr("app.tools.runtime_impl._runtime_workspace_cli.execute_with_runtime", fake_execute_with_runtime)
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool("run_cli_command", {"command": "terraform validate"}, context)

    assert result["exit_code"] == 127
    assert result["validation_outcome"]["status"] == "missing_tool"
    assert result["validation_outcome"]["blocker"] == "validation_tool_missing"
    assert result["execution_event"]["kind"] == "validation"
    assert result["execution_event"]["metadata"]["validation_outcome"]["status"] == "missing_tool"


@pytest.mark.asyncio
async def test_run_cli_command_validation_outcome_wrong_cwd(tmp_path):
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )

    result = await execute_tool("run_cli_command", {"command": "terraform validate", "cwd": "../outside"}, context)

    assert result["validation_outcome"]["status"] == "wrong_cwd"
    assert result["validation_outcome"]["blocker"] == "validation_cwd_invalid"
    # The platform-side cwd error is classified into status/blocker; its text is not evidence.
    assert result["validation_outcome"]["evidence"]["stderr_excerpt"] == ""


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_cli_command_rejects_shell_control_operators():
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["operator"],
        session_id="s1",
        project_config={},
        workspace_root=str(Path.cwd()),
    )

    result = await execute_tool("run_cli_command", {"command": "printf hello && whoami"}, context)

    assert "only supports direct executable invocations" in result["error"]
