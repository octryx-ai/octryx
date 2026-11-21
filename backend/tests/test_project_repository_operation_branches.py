"""Bitbucket branch creation, repository preparation and commit-and-push follow the project branch and write policies."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import CodeRepository, Project
from app.tools.bitbucket_impl._bitbucket_branches import CreateBitbucketBranch
from app.tools.bitbucket_impl._bitbucket_sync_repo import CommitAndPushRepositoryBranch, PrepareBitbucketRepository
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_create_bitbucket_branch_respects_project_repository_branch_policy(db, monkeypatch):
    project = Project(name="repo-branch-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"branch": False}},
        )
    )
    await db.commit()

    post_calls: list[dict] = []

    async def fake_post(*args, **kwargs):
        post_calls.append({"args": args, "kwargs": kwargs})
        return {}, 200

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_branches._bitbucket_json_post", fake_post)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=[],
        session_id="session-1",
        db=db,
        workspace_root=str(Path.cwd()),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await CreateBitbucketBranch().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "branch_name": "feature/update-service-api",
            "start_point": "master",
        },
        context,
    )

    assert "error" in result
    assert "branch" in result["error"]
    assert post_calls == []


@pytest.mark.asyncio
async def test_configured_bitbucket_repository_can_create_branch_with_source_control_evidence(db, monkeypatch):
    project = Project(name="repo-branch-create-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"read": True, "branch": True, "write": True, "pr": True}},
        )
    )
    await db.commit()

    async def fake_post(_context, _path, *, payload):
        return {"displayId": payload["name"], "latestCommit": "abc123"}, 200

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_branches._bitbucket_json_post", fake_post)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=[],
        session_id="session-1",
        db=db,
        workspace_root=str(Path.cwd()),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await CreateBitbucketBranch().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "branch_name": "feature/update-service-api",
            "start_point": "master",
        },
        context,
    )

    assert result["status"] == "created"
    assert result["source_control"]["operation"] == "create_branch"
    assert result["source_control"]["repository_operation"] == "branch"
    assert result["source_control"]["provider"] == "bitbucket"
    source_control_payload = str(
        {"output": result["source_control"]["output"], "evidence": result["source_control"]["evidence"]}
    ).lower()
    assert "secret" not in source_control_payload


@pytest.mark.asyncio
async def test_prepare_bitbucket_repository_respects_project_repository_branch_policy(db, monkeypatch, tmp_path):
    project = Project(name="repo-prepare-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root=str(tmp_path / "service-api"),
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"branch": False}},
        )
    )
    await db.commit()

    git_calls: list[list[str]] = []

    async def fake_run_git(command, **kwargs):
        git_calls.append(command)
        return 0, "", ""

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_sync_repo._run_git", fake_run_git)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=[],
        session_id="session-1",
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_username": "user",
            "bitbucket_token": "token",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await PrepareBitbucketRepository().execute(
        {"project_key": "PROJ", "repo_slug": "service-api", "branch_name": "feature/update-service-api"},
        context,
    )

    assert "error" in result
    assert "branch" in result["error"]
    assert git_calls == []


@pytest.mark.asyncio
async def test_commit_and_push_repository_branch_respects_project_repository_write_policy(db, monkeypatch, tmp_path):
    project = Project(name="repo-write-policy-project", config={}, is_active=True)
    repo_path = tmp_path / "service-api"
    git_dir = repo_path / ".git"
    git_dir.mkdir(parents=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root=str(repo_path),
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"write": False}},
        )
    )
    await db.commit()

    git_calls: list[list[str]] = []

    async def fake_run_git(command, **kwargs):
        git_calls.append(command)
        return 0, "", ""

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_sync_repo._run_git", fake_run_git)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=[],
        session_id="session-1",
        db=db,
        workspace_root=str(tmp_path),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await CommitAndPushRepositoryBranch().execute(
        {
            "local_path": str(repo_path),
            "repo_slug": "service-api",
            "commit_message": "docs: update service api",
        },
        context,
    )

    assert "error" in result
    assert "write" in result["error"]
    assert git_calls == []
