"""Bash and CLI routing refuse ambiguous repository candidates, and exec policy config cannot admit an unbound read command."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ExecPolicyConfig, User
from app.services.security_analyzer import analyze_security_risk
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_turn_execution_pipeline_support import _server_pipeline  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bash_tool_returns_ambiguity_error_for_multiple_manage_py_candidates(monkeypatch, tmp_path):
    repo_a = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "service-a"
    repo_b = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "service-b"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)
    (repo_a / "manage.py").write_text("print('a')\n", encoding="utf-8")
    (repo_b / "manage.py").write_text("print('b')\n", encoding="utf-8")

    called = {"value": False}

    async def fake_shell(command, **kwargs):
        called["value"] = True
        raise AssertionError("subprocess should not run when repository resolution is ambiguous")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="test",
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "service-a", "enabled": True},
                {"project_key": "SHOP", "repo_slug": "service-b", "enabled": True},
            ],
        },
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("bash", {"command": "python3 manage.py migrate"}, context)

    assert "ambiguous" in result["error"].lower()
    assert result["script_resolution"]["candidate_count"] == 2
    assert len(result["script_resolution"]["candidates"]) == 2
    assert called["value"] is False


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_cli_command_returns_ambiguity_error_for_multiple_package_json_repos(monkeypatch, tmp_path):
    repo_a = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "frontend-a"
    repo_b = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "frontend-b"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)
    (repo_a / "package.json").write_text('{"name":"frontend-a"}\n', encoding="utf-8")
    (repo_b / "package.json").write_text('{"name":"frontend-b"}\n', encoding="utf-8")

    called = {"value": False}

    async def fake_shell(command, **kwargs):
        called["value"] = True
        raise AssertionError("subprocess should not run when npm repo resolution is ambiguous")

    monkeypatch.setattr("asyncio.create_subprocess_shell", fake_shell)

    context = ToolContext(
        user_id="test",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="test",
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "frontend-a", "enabled": True},
                {"project_key": "SHOP", "repo_slug": "frontend-b", "enabled": True},
            ],
        },
        capability_type="change",
        workspace_root=str(tmp_path),
    )
    result = await execute_tool("run_cli_command", {"command": "npm install"}, context)

    assert "multiple allowed repositories" in result["error"].lower()
    assert result["script_resolution"]["repo_resolution"]["candidate_count"] == 2
    assert len(result["script_resolution"]["repo_resolution"]["repo_candidates"]) == 2
    assert called["value"] is False


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_exec_policy_config_cannot_admit_a_read_command_without_an_option_binding(db):
    """The read-only list is bound to closed option tables; an admin-added program
    without one (``python3`` can write or run anything) fails closed instead of being allowed."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    db.add(
        ExecPolicyConfig(
            id=str(uuid.uuid4()),
            name="Global Exec Policy",
            project_id=None,
            priority=100,
            is_active=True,
            config_json={
                "diagnosis_read_only_commands": ["python3"],
            },
        )
    )
    await db.commit()

    context = ToolContext(
        user_id=admin.id,
        project_ids=[],
        roles=["admin"],
        session_id="policy-test",
        project_config={},
        run_capability={"enforced": True, "class": "read_only"},
        workspace_root=str(Path.cwd()),
        db=db,
    )

    decision = await analyze_security_risk("bash", "python3 --version", context)
    assert decision.action == "review"
