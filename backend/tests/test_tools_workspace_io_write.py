"""Tests for workspace file I/O tools, system context, and script execution."""

import subprocess

import pytest

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
async def test_write_workspace_file_tool(tmp_path):
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )
    result = await execute_tool(
        "write_workspace_file",
        {"path": "repo/README.md", "content": "# Demo\nHello world"},
        context,
    )
    assert result["path"].endswith("repo/README.md")
    assert result["execution_event"]["kind"] == "write"
    assert result["execution_event"]["status"] == "succeeded"
    assert result["execution_event"]["tool_name"] == "write_workspace_file"
    assert result["execution_event"]["metadata"]["target_paths"] == ["repo/README.md"]
    assert (tmp_path / "repo" / "README.md").read_text(encoding="utf-8") == "# Demo\nHello world\n"
    assert result["workspace_sync"]["status"] == "skipped"
    assert result["workspace_sync"]["reason"] == "db_unavailable"


@pytest.mark.asyncio
async def test_write_workspace_file_blocks_preexisting_dirty_target(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    target = repo / "README.md"
    target.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True)
    target.write_text("user change\n", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(repo),
    )
    result = await execute_tool(
        "write_workspace_file",
        {"path": "README.md", "content": "agent change"},
        context,
    )

    assert "Refusing to overwrite" in result["error"]
    assert target.read_text(encoding="utf-8") == "user change\n"
    contract = result["workspace_change_contract"]
    assert contract["blocked_paths"] == ["README.md"]
    assert "preexisting_dirty_target_blocked" in contract["risk_markers"]


@pytest.mark.asyncio
async def test_write_workspace_file_dirty_target_override_records_risk(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    target = repo / "README.md"
    target.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True)
    target.write_text("user change\n", encoding="utf-8")

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(repo),
    )
    result = await execute_tool(
        "write_workspace_file",
        {"path": "README.md", "content": "agent change", "allow_overwrite_dirty": True},
        context,
    )

    assert result["bytes_written"] == len(b"agent change\n")
    assert target.read_text(encoding="utf-8") == "agent change\n"
    contract = result["workspace_change_contract"]
    assert contract["target_paths"] == ["README.md"]
    assert "dirty_target_override_used" in contract["risk_markers"]
    assert "workspace_dirty_before" in contract["risk_markers"]


@pytest.mark.asyncio
async def test_write_workspace_file_tool_syncs_to_filesystem_workspace_storage(db, tmp_path):
    storage_root = tmp_path / "objects"
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY, value="filesystem")
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY, value=str(storage_root))
    await set_system_config_value(db, key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY, value="octryx/dev")
    await db.commit()

    from app.models import Session

    session = Session(id="sync-session-1", user_id="user-1", metadata_={})
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
    result = await execute_tool(
        "write_workspace_file",
        {"path": "repo/README.md", "content": "# Demo\nHello world"},
        context,
    )

    assert result["workspace_sync"]["status"] == "synced"
    assert result["workspace_sync"]["backend"] == "filesystem"
    assert result["workspace_sync"]["key"] == "octryx/dev/sessions/sync-session-1/workspace/current/repo/README.md"
    assert (
        storage_root / "octryx" / "dev" / "sessions" / "sync-session-1" / "workspace" / "current" / "repo" / "README.md"
    ).read_text(encoding="utf-8") == "# Demo\nHello world\n"
    assert session.metadata_["workspace_storage"]["backend"] == "filesystem"


@pytest.mark.asyncio
async def test_write_workspace_file_tool_reports_sync_error_without_rolling_back(monkeypatch, tmp_path):
    from app.tools.runtime_impl import _runtime_workspace_files

    async def fake_sync_workspace_file_after_write(**_kwargs):
        return {"status": "error", "error": "mirror failed"}

    monkeypatch.setattr(
        _runtime_workspace_files, "sync_workspace_file_after_write", fake_sync_workspace_file_after_write
    )

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={},
        workspace_root=str(tmp_path),
    )
    result = await execute_tool(
        "write_workspace_file",
        {"path": "repo/README.md", "content": "# Demo"},
        context,
    )

    assert (tmp_path / "repo" / "README.md").read_text(encoding="utf-8") == "# Demo\n"
    assert result["workspace_sync"] == {"status": "error", "error": "mirror failed"}
