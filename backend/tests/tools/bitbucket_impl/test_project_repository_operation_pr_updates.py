"""Bitbucket pull request updates with source control evidence and under the project PR policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import CodeRepository, Project
from app.tools.bitbucket_impl._bitbucket_pull_requests import UpdateBitbucketPullRequest
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_configured_bitbucket_repository_can_update_pull_request_with_source_control_evidence(db, monkeypatch):
    project = Project(name="repo-pr-update-project", config={}, is_active=True)
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

    async def fake_get(*args, **kwargs):
        return {
            "id": 42,
            "version": 3,
            "title": "Old title",
            "description": "Old description",
            "state": "OPEN",
            "fromRef": {"id": "refs/heads/feature/existing", "displayId": "feature/existing"},
            "toRef": {"id": "refs/heads/master", "displayId": "master"},
            "reviewers": [],
            "links": {"self": [{"href": "https://bitbucket.example/projects/PROJ/repos/service-api/pull-requests/42"}]},
        }

    put_calls: list[dict] = []

    async def fake_put(_context, _path, *, payload):
        put_calls.append(payload)
        return {
            **payload,
            "state": "OPEN",
            "fromRef": payload["fromRef"],
            "toRef": payload["toRef"],
            "links": {"self": [{"href": "https://bitbucket.example/projects/PROJ/repos/service-api/pull-requests/42"}]},
        }, 200

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_put", fake_put)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=["admin"],
        session_id="session-1",
        db=db,
        workspace_root=str(Path.cwd()),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await UpdateBitbucketPullRequest().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "pr_id": 42,
            "description": "Updated description",
            "to_branch": "main",
            "reviewers": ["reviewerbb"],
        },
        context,
    )

    assert result["status"] == "updated"
    assert put_calls[0]["version"] == 3
    assert put_calls[0]["toRef"]["displayId"] == "main"
    assert put_calls[0]["reviewers"] == [{"user": {"name": "reviewerbb"}}]
    assert result["source_control"]["operation"] == "update_change_request"
    assert result["source_control"]["repository_operation"] == "pr"
    assert result["source_control"]["evidence"]["updated_fields"] == ["description", "to_branch", "reviewers"]
    source_control_payload = str(
        {"output": result["source_control"]["output"], "evidence": result["source_control"]["evidence"]}
    ).lower()
    assert "secret" not in source_control_payload
    assert "authorization" not in source_control_payload


@pytest.mark.asyncio
async def test_update_bitbucket_pull_request_respects_project_repository_pr_policy(db, monkeypatch):
    project = Project(name="repo-pr-update-denied-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    db.add(
        CodeRepository(
            project_id=project.id,
            name="service-api",
            provider="bitbucket",
            repo_root="/workspace/service-api",
            remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
            config_json={"operation_policy": {"read": True, "pr": False}},
        )
    )
    await db.commit()

    get_calls: list[dict] = []
    put_calls: list[dict] = []

    async def fake_get(*args, **kwargs):
        get_calls.append({"args": args, "kwargs": kwargs})
        return {}

    async def fake_put(*args, **kwargs):
        put_calls.append({"args": args, "kwargs": kwargs})
        return {}, 200

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_put", fake_put)

    context = ToolContext(
        user_id="user-1",
        project_ids=[project.id],
        roles=["admin"],
        session_id="session-1",
        db=db,
        workspace_root=str(Path.cwd()),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )

    result = await UpdateBitbucketPullRequest().execute(
        {"project_key": "PROJ", "repo_slug": "service-api", "pr_id": 42, "description": "Updated"},
        context,
    )

    assert "error" in result
    assert "pr" in result["error"]
    assert get_calls == []
    assert put_calls == []
