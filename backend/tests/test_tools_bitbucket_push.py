"""Committing and pushing a branch, credential redaction in git output and the repository allowlist."""

import json

import pytest

from app.tools.bitbucket_impl._bitbucket_internal_core import _redact_bitbucket_git_output
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.tools_bitbucket_support import _create_bitbucket_policy_project


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_commit_and_push_repository_branch_tool(tmp_path, monkeypatch, db):
    repo_path = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / ".git").mkdir(exist_ok=True)
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_path))
    commands: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        commands.append(list(args))

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                if list(args[:3]) == ["git", "status", "--porcelain"]:
                    return (b" M README.md\n", b"")
                if list(args[:4]) == ["git", "branch", "--show-current"]:
                    return (b"codex/readme-acme-orders\n", b"")
                if list(args[:3]) == ["git", "rev-parse", "HEAD"]:
                    return (b"def456\n", b"")
                return (b"", b"")

        return FakeProcess()

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
            "tool_policy": {"allowlist": ["commit_and_push_repository_branch"]},
        },
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "commit_and_push_repository_branch",
        {"local_path": str(repo_path), "commit_message": "docs: add README"},
        context,
    )
    assert result["status"] == "pushed"
    assert result["branch_name"] == "codex/readme-acme-orders"
    assert result["head_commit"] == "def456"
    assert any(command[:3] == ["git", "add", "-A"] for command in commands)
    assert any(command[:3] == ["git", "push", "--set-upstream"] for command in commands)
    assert result["source_control"]["operation"] == "push"
    assert result["source_control"]["repository_operation"] == "write"
    assert result["source_control"]["provider"] == "bitbucket"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_commit_and_push_repository_branch_tool_accepts_message_alias(tmp_path, monkeypatch, db):
    repo_path = tmp_path / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / ".git").mkdir(exist_ok=True)
    project_id = await _create_bitbucket_policy_project(db, repo_root=str(repo_path))

    async def fake_exec(*args, **kwargs):
        class FakeProcess:
            returncode = 0

            async def communicate(self):
                if list(args[:3]) == ["git", "status", "--porcelain"]:
                    return (b" M README.md\n", b"")
                if list(args[:4]) == ["git", "branch", "--show-current"]:
                    return (b"codex/readme-acme-orders\n", b"")
                if list(args[:3]) == ["git", "rev-parse", "HEAD"]:
                    return (b"def456\n", b"")
                return (b"", b"")

        return FakeProcess()

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
            "tool_policy": {"allowlist": ["commit_and_push_repository_branch"]},
        },
        workspace_root=str(tmp_path),
    )

    result = await execute_tool(
        "commit_and_push_repository_branch",
        {"local_path": str(repo_path), "message": "docs: add README"},
        context,
    )
    assert result["status"] == "pushed"
    assert result["source_control"]["operation"] == "push"


def test_bitbucket_git_output_redacts_connector_credentials():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["operator"],
        session_id="test",
        project_config={
            "bitbucket_username": "alice",
            "bitbucket_token": "super-secret-token",
        },
    )

    output = _redact_bitbucket_git_output(
        context,
        "fatal: https://alice:super-secret-token@bitbucket.example/scm/PROJ/repo.git "
        "password=super-secret-token token=super-secret-token",
    )

    assert "super-secret-token" not in output
    assert "alice:super-secret-token" not in output
    assert "password=[redacted]" in output
    assert "token=[redacted]" in output


class _FakeTextResponse:
    status_code = 200
    text = "print('ok')"

    def raise_for_status(self):
        return None


class _FakeJsonResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAllowlistClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, headers=None, auth=None, params=None):
        if "/commits/" in url and "/changes" in url:
            return _FakeJsonResponse(
                {
                    "values": [
                        {
                            "path": {"components": ["values.yaml"]},
                            "srcPath": {"components": ["values-old.yaml"]},
                            "type": "MOVE",
                            "executable": False,
                        }
                    ]
                }
            )
        if url.endswith("/commits"):
            return _FakeJsonResponse(
                {
                    "values": [
                        {
                            "id": "abc123",
                            "displayId": "abc123",
                            "message": "Update app ini values",
                            "author": {"name": "alice", "emailAddress": "alice@example.com"},
                            "authorTimestamp": 1734379500,
                        }
                    ]
                }
            )
        if "/browse" in url:
            return _FakeJsonResponse(
                {
                    "children": {
                        "values": [
                            {"path": {"components": ["README.md"]}, "type": "FILE"},
                            {"path": {"components": ["src"]}, "type": "DIRECTORY"},
                        ]
                    }
                }
            )
        assert "projects/RIVER/repos/service-config/raw/app.py" in url
        assert auth == ("alice", "secret")
        return _FakeTextResponse()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_bitbucket_tools_enforce_repo_allowlist(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: _FakeAllowlistClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "bitbucket_auth_mode": "basic",
            "bitbucket_url": "https://bitbucket.example.com/bitbucket",
            "bitbucket_username": "alice",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
    )
    listed = await execute_tool("list_bitbucket_repositories", {}, context)
    assert listed["repositories"][0]["project_key"] == "RIVER"
    directory = await execute_tool(
        "list_bitbucket_directory",
        {"project_key": "RIVER", "repo_slug": "service-config", "path": ""},
        context,
    )
    assert directory["entries"][0]["path"] == "README.md"
    commits = await execute_tool(
        "list_bitbucket_commits",
        {"project_key": "RIVER", "repo_slug": "service-config"},
        context,
    )
    assert commits["commits"][0]["id"] == "abc123"
    changes = await execute_tool(
        "get_bitbucket_commit_changes",
        {"project_key": "RIVER", "repo_slug": "service-config", "commit_id": "abc123"},
        context,
    )
    assert changes["changes"][0]["path"] == "values.yaml"

    allowed = await execute_tool(
        "read_bitbucket_file",
        {"project_key": "RIVER", "repo_slug": "service-config", "path": "app.py"},
        context,
    )
    assert "print('ok')" in allowed["content"]

    denied = await execute_tool(
        "read_bitbucket_file",
        {"project_key": "OPS", "repo_slug": "runbooks", "path": "README.md"},
        context,
    )
    assert "not allowed" in denied["error"]
