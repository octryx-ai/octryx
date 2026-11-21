"""Preparing a Bitbucket repository: the clone, an existing origin updated without credentials and the detected branch fallback."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_bitbucket_support import _create_bitbucket_policy_project


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_bitbucket_repository_tool(tmp_path, monkeypatch, db):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []
    envs: list[dict[str, str] | None] = []

    async def fake_json_get(context, path, params=None):
        assert path.endswith("/branches/default")
        return {"displayId": "main"}

    async def fake_exec(*args, **kwargs):
        commands.append(list(args))
        envs.append(kwargs.get("env"))

        class FakeProcess:
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                if list(args[:3]) == ["git", "rev-parse", "HEAD"]:
                    return (b"abc123\n", b"")
                if list(args[:2]) == ["git", "clone"]:
                    repo_root.mkdir(parents=True, exist_ok=True)
                    (repo_root / ".git").mkdir(exist_ok=True)
                return (b"", b"")

        return FakeProcess()

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_json_get)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=[project_id],
        roles=["operator"],
        session_id="test",
        db=db,
        project_config={
            "bitbucket_auth_mode": "basic",
            "bitbucket_url": "https://scm.example.test/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin", "enabled": True}
            ],
            "managed_repo_root": "var/repos/bitbucket",
            "tool_policy": {"allowlist": ["prepare_bitbucket_repository"]},
        },
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "prepare_bitbucket_repository",
        {"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin", "branch_name": "codex/readme-acme-orders"},
        context,
    )
    assert result["branch_name"] == "codex/readme-acme-orders"
    assert result["base_branch"] == "main"
    assert result["cloned"] is True
    assert result["local_path"] == str(repo_root)
    assert result["relative_path"] == "var/repos/bitbucket/SHOP/acme-orders-catalog-plugin"
    clone_command = next(command for command in commands if command[:2] == ["git", "clone"])
    clone_url = clone_command[-2]
    assert clone_url == "https://scm.example.test/bitbucket/scm/SHOP/acme-orders-catalog-plugin.git"
    assert result["remote_url"] == clone_url
    assert "secret" not in " ".join(" ".join(command) for command in commands)
    assert "user:secret" not in " ".join(" ".join(command) for command in commands)
    assert any(env and env.get("OCTRYX_BITBUCKET_SECRET") == "secret" for env in envs)
    assert result["source_control"]["operation"] == "prepare_repository"
    assert result["source_control"]["repository_operation"] == "branch"
    assert result["source_control"]["provider"] == "bitbucket"


@pytest.mark.asyncio
async def test_prepare_bitbucket_repository_updates_existing_origin_without_credentials(tmp_path, monkeypatch, db):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    (repo_root / ".git").mkdir(parents=True)
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []

    async def fake_json_get(context, path, params=None):
        assert path.endswith("/branches/default")
        return {"displayId": "main"}

    async def fake_exec(*args, **kwargs):
        command = list(args)
        commands.append(command)

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                if command[:3] == ["git", "rev-parse", "HEAD"]:
                    return (b"abc123\n", b"")
                return (b"", b"")

        return FakeProcess()

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_json_get)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=[project_id],
        roles=["operator"],
        session_id="test",
        db=db,
        project_config={
            "bitbucket_auth_mode": "basic",
            "bitbucket_url": "https://scm.example.test/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin", "enabled": True}
            ],
            "managed_repo_root": "var/repos/bitbucket",
            "tool_policy": {"allowlist": ["prepare_bitbucket_repository"]},
        },
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "prepare_bitbucket_repository",
        {"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin", "branch_name": "codex/readme-acme-orders"},
        context,
    )

    clean_url = "https://scm.example.test/bitbucket/scm/SHOP/acme-orders-catalog-plugin.git"
    remote_set_url_command = next(command for command in commands if command[:4] == ["git", "remote", "set-url", "origin"])
    assert remote_set_url_command[-1] == clean_url
    assert result["remote_url"] == clean_url
    assert "secret" not in " ".join(" ".join(command) for command in commands)
    assert result["source_control"]["operation"] == "prepare_repository"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_prepare_bitbucket_repository_tool_falls_back_to_detected_branch(tmp_path, monkeypatch, db):
    repo_root = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []

    async def fake_json_get(context, path, params=None):
        assert path.endswith("/branches/default")
        return {"displayId": "master"}

    async def fake_exec(*args, **kwargs):
        command = list(args)
        commands.append(command)

        class FakeProcess:
            def __init__(self, returncode=0, stdout=b"", stderr=b""):
                self.returncode = returncode
                self._stdout = stdout
                self._stderr = stderr

            async def communicate(self):
                if command[:3] == ["git", "rev-parse", "HEAD"]:
                    return (b"abc123\n", b"")
                if command[:2] == ["git", "clone"] and "--branch" in command:
                    branch = command[command.index("--branch") + 1]
                    if branch == "main":
                        return (b"", b"fatal: Remote branch main not found in upstream origin\n")
                    repo_root.mkdir(parents=True, exist_ok=True)
                    (repo_root / ".git").mkdir(exist_ok=True)
                return (self._stdout, self._stderr)

        if command[:2] == ["git", "clone"] and "--branch" in command:
            branch = command[command.index("--branch") + 1]
            if branch == "main":
                return FakeProcess(returncode=1, stderr=b"fatal: Remote branch main not found in upstream origin\n")
        return FakeProcess()

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_json_get)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    context = ToolContext(
        user_id="test",
        project_ids=[project_id],
        roles=["operator"],
        session_id="test",
        db=db,
        project_config={
            "bitbucket_auth_mode": "basic",
            "bitbucket_url": "https://scm.example.test/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-catalog-plugin", "enabled": True}
            ],
            "managed_repo_root": "var/repos/bitbucket",
            "tool_policy": {"allowlist": ["prepare_bitbucket_repository"]},
        },
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "prepare_bitbucket_repository",
        {
            "project_key": "SHOP",
            "repo_slug": "acme-orders-catalog-plugin",
            "base_branch": "main",
            "branch_name": "codex/readme-acme-orders",
        },
        context,
    )
    assert result["base_branch"] == "master"
    assert result["fallback_used"] is True
    assert result["attempted_base_branches"] == ["main", "master"]
    assert result["source_control"]["operation"] == "prepare_repository"
