from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from app.models import CodeRepository, Project
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


async def _create_gitlab_project(db, *, repo_root: str = "/workspace/octryx", policy: dict | None = None) -> str:
    project = Project(name="gitlab-source-control-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="octryx",
            provider="gitlab",
            repo_root=repo_root,
            remote_url="https://gitlab.example/group/octryx.git",
            default_branch="main",
            config_json={
                "operation_policy": policy
                or {"read": True, "branch": True, "write": True, "pr": True, "index": True, "migration": False}
            },
        )
    )
    await db.commit()
    return project.id


def _gitlab_context(project_id: str, *, db, workspace_root: str | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=[project_id],
        roles=["admin"],
        session_id="session-1",
        db=db,
        workspace_root=workspace_root or str(Path.cwd()),
        project_config={
            "gitlab_url": "https://gitlab.example",
            "gitlab_token": "gl-token",
            "gitlab_allowed_projects": ["group/octryx"],
            "managed_repo_root": "var/repos/gitlab",
            "tool_policy": {
                "allowlist": [
                    "read_gitlab_file",
                    "list_gitlab_branches",
                    "create_gitlab_branch",
                    "prepare_gitlab_repository",
                    "commit_and_push_gitlab_repository_branch",
                    "list_gitlab_merge_requests",
                    "get_gitlab_merge_request",
                    "create_gitlab_merge_request",
                    "update_gitlab_merge_request",
                    "list_gitlab_pipelines",
                ]
            },
        },
    )


def _mr_payload(iid: int = 9, *, title: str = "MR title", target: str = "main") -> dict[str, Any]:
    return {
        "iid": iid,
        "title": title,
        "state": "opened",
        "author": {"username": "alice"},
        "source_branch": "codex/test",
        "target_branch": target,
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "web_url": f"https://gitlab.example/group/octryx/-/merge_requests/{iid}",
    }


@pytest.mark.asyncio
async def test_gitlab_provider_owned_read_branch_mr_and_pipeline_tools_are_policy_bound(db, monkeypatch):
    project_id = await _create_gitlab_project(db)
    http_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30):
        assert headers["PRIVATE-TOKEN"] == "gl-token"
        assert "gl-token" not in url
        http_calls.append((method, url, json_body))
        if method == "GET" and url.endswith("/repository/files/README.md"):
            return {
                "content": base64.b64encode(b"hello gitlab").decode("ascii"),
                "encoding": "base64",
                "size": 12,
                "content_sha256": "file-sha",
            }
        if method == "GET" and url.endswith("/repository/branches"):
            return [{"name": "main", "commit": {"id": "main-sha"}, "protected": True}]
        if method == "POST" and url.endswith("/repository/branches"):
            assert params == {"branch": "codex/test", "ref": "main"}
            return {"name": "codex/test", "commit": {"id": "main-sha"}}
        if method == "GET" and url.endswith("/merge_requests"):
            return [_mr_payload()]
        if method == "GET" and url.endswith("/merge_requests/9"):
            return _mr_payload()
        if method == "POST" and url.endswith("/merge_requests"):
            assert json_body == {
                "title": "MR title",
                "source_branch": "codex/test",
                "target_branch": "main",
                "description": "MR body",
            }
            return _mr_payload()
        if method == "PUT" and url.endswith("/merge_requests/9"):
            assert json_body == {"description": "Updated", "target_branch": "develop"}
            return _mr_payload(target="develop")
        if method == "GET" and url.endswith("/pipelines"):
            return [{"id": 12, "status": "success", "ref": "main", "sha": "abc", "web_url": "https://gitlab.example/p/12"}]
        raise AssertionError(f"unexpected GitLab request: {method} {url}")

    monkeypatch.setattr("app.tools.connectors.gitlab_source_control._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.gitlab_merge_requests._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.gitlab._http_json", fake_http_json)

    context = _gitlab_context(project_id, db=db)
    read_result = await execute_tool("read_gitlab_file", {"project": "group/octryx", "path": "README.md", "ref": "main"}, context)
    branches_result = await execute_tool("list_gitlab_branches", {"project": "group/octryx"}, context)
    branch_result = await execute_tool(
        "create_gitlab_branch",
        {"project": "group/octryx", "branch_name": "codex/test", "start_point": "main"},
        context,
    )
    list_mr_result = await execute_tool("list_gitlab_merge_requests", {"project": "group/octryx"}, context)
    get_mr_result = await execute_tool("get_gitlab_merge_request", {"project": "group/octryx", "mr_iid": 9}, context)
    create_mr_result = await execute_tool(
        "create_gitlab_merge_request",
        {
            "project": "group/octryx",
            "title": "MR title",
            "from_branch": "codex/test",
            "to_branch": "main",
            "description": "MR body",
        },
        context,
    )
    update_mr_result = await execute_tool(
        "update_gitlab_merge_request",
        {"project": "group/octryx", "mr_iid": 9, "description": "Updated", "to_branch": "develop"},
        context,
    )
    pipelines_result = await execute_tool("list_gitlab_pipelines", {"project": "group/octryx"}, context)

    assert read_result["content"] == "hello gitlab"
    assert read_result["source_control"]["operation"] == "read_file"
    assert branches_result["source_control"]["operation"] == "list_branches"
    assert branch_result["source_control"]["operation"] == "create_branch"
    assert list_mr_result["source_control"]["operation"] == "list_change_requests"
    assert get_mr_result["source_control"]["operation"] == "get_change_request"
    assert create_mr_result["source_control"]["operation"] == "create_change_request"
    assert update_mr_result["source_control"]["operation"] == "update_change_request"
    assert pipelines_result["source_control"]["operation"] == "list_pipelines"
    safe_payload = str({"read": read_result.get("source_control"), "mr": create_mr_result.get("source_control")}).lower()
    assert "gl-token" not in safe_payload
    assert "private-token" not in safe_payload
    assert http_calls


@pytest.mark.asyncio
async def test_prepare_gitlab_repository_uses_clean_clone_url_and_source_control_metadata(db, monkeypatch, tmp_path):
    repo_root = tmp_path / "var" / "repos" / "gitlab" / "group" / "octryx"
    project_id = await _create_gitlab_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []
    envs: list[dict[str, str] | None] = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        commands.append(list(command))
        envs.append(env)
        if command[:2] == ["git", "clone"]:
            assert command[-2] == "https://gitlab.example/group/octryx.git"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(exist_ok=True)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123\n", ""
        return 0, "", ""

    monkeypatch.setattr("app.tools.connectors.gitlab_repository_prepare._run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "prepare_gitlab_repository",
        {"project": "group/octryx", "base_branch": "main", "branch_name": "codex/test"},
        _gitlab_context(project_id, db=db, workspace_root=str(tmp_path)),
    )

    assert result["source_control"]["operation"] == "prepare_repository"
    assert result["remote_url"] == "https://gitlab.example/group/octryx.git"
    assert result["relative_path"] == "var/repos/gitlab/group/octryx"
    assert "gl-token" not in " ".join(" ".join(command) for command in commands)
    assert any(env and env.get("OCTRYX_GITLAB_SECRET") == "gl-token" for env in envs)
    assert "gl-token" not in str(result).lower()


@pytest.mark.asyncio
async def test_commit_and_push_gitlab_repository_branch_uses_clean_remote_and_policy(db, monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    project_id = await _create_gitlab_project(db, repo_root=str(repo_root))
    commands: list[list[str]] = []

    async def fake_run_subprocess(command, *, env=None, cwd=None):
        commands.append(list(command))
        if command[:3] == ["git", "status", "--porcelain"]:
            return 0, " M README.md\n", ""
        if command[:3] == ["git", "branch", "--show-current"]:
            return 0, "codex/test\n", ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return 0, "def456\n", ""
        return 0, "", ""

    monkeypatch.setattr("app.tools.connectors.gitlab_repository_push._run_subprocess", fake_run_subprocess)

    result = await execute_tool(
        "commit_and_push_gitlab_repository_branch",
        {
            "project": "group/octryx",
            "local_path": str(repo_root),
            "commit_message": "docs: update README",
        },
        _gitlab_context(project_id, db=db, workspace_root=str(tmp_path)),
    )

    assert result["status"] == "pushed"
    assert result["source_control"]["operation"] == "push"
    remote_set_url = next(command for command in commands if command[:4] == ["git", "remote", "set-url", "origin"])
    assert remote_set_url[-1] == "https://gitlab.example/group/octryx.git"
    assert "gl-token" not in " ".join(" ".join(command) for command in commands)
    assert "gl-token" not in str(result).lower()


@pytest.mark.asyncio
async def test_gitlab_mutations_stop_before_provider_calls_when_repository_policy_denies(db, monkeypatch):
    project_id = await _create_gitlab_project(
        db,
        policy={"read": True, "branch": False, "write": False, "pr": False, "index": True, "migration": False},
    )
    http_calls: list[tuple] = []

    async def fake_http_json(*args, **kwargs):
        http_calls.append((args, kwargs))
        return {}

    monkeypatch.setattr("app.tools.connectors.gitlab_source_control._http_json", fake_http_json)
    monkeypatch.setattr("app.tools.connectors.gitlab_merge_requests._http_json", fake_http_json)

    context = _gitlab_context(project_id, db=db)
    branch_result = await execute_tool(
        "create_gitlab_branch",
        {"project": "group/octryx", "branch_name": "codex/test", "start_point": "main"},
        context,
    )
    mr_result = await execute_tool(
        "create_gitlab_merge_request",
        {"project": "group/octryx", "title": "MR title", "from_branch": "codex/test", "to_branch": "main"},
        context,
    )

    assert "branch" in branch_result["error"]
    assert "pr" in mr_result["error"]
    assert http_calls == []
