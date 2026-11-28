"""Bitbucket pull request creation follows the project PR policy, registered reviewer profiles and existing source branch PRs."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.models import CodeRepository, Project, Session, WorkItem, WorkItemChangeUnit, WorkRepositoryProfile
from app.tools.bitbucket_impl._bitbucket_pull_requests import CreateBitbucketPullRequest
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_create_bitbucket_pull_request_respects_project_repository_pr_policy(db, monkeypatch):
    project = Project(name="repo-pr-policy-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    repo = CodeRepository(
        project_id=project.id,
        name="service-api",
        provider="bitbucket",
        repo_root="/workspace/service-api",
        remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
        config_json={
            "operation_policy": {
                "read": True,
                "pr": False,
            }
        },
    )
    db.add(repo)
    await db.commit()

    post_calls: list[dict] = []

    async def fake_post(*args, **kwargs):
        post_calls.append({"args": args, "kwargs": kwargs})
        return {}, 201

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_post", fake_post)

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

    result = await CreateBitbucketPullRequest().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "title": "Update service API",
            "from_branch": "feature/update-service-api",
            "to_branch": "master",
        },
        context,
    )

    assert "error" in result
    assert "pr" in result["error"]
    assert post_calls == []


def _bitbucket_tool_context(db, project_id: str, *, user_id: str, roles: list[str], session_id: str) -> ToolContext:
    return ToolContext(
        user_id=user_id,
        project_ids=[project_id],
        roles=roles,
        session_id=session_id,
        db=db,
        workspace_root=str(Path.cwd()),
        project_config={
            "bitbucket_url": "https://bitbucket.example",
            "bitbucket_allowed_repos": ["PROJ/service-api"],
        },
    )


async def _seed_reviewer_change_unit_session(db, actor, project) -> Session:
    repo = CodeRepository(
        project_id=project.id,
        name="service-api",
        provider="bitbucket",
        repo_root="/workspace/service-api",
        remote_url="https://bitbucket.example/scm/PROJ/service-api.git",
        config_json={"operation_policy": {"read": True, "branch": True, "write": True, "pr": True}},
    )
    item = WorkItem(
        project_id=project.id,  # the session's Workspace: an item of another one is never used
        source_type="jira",
        source_instance="risk",
        source_key="ACME-615",
        title="Clean Terraform leftovers",
        sync_state="imported",
        labels_json=["octryx"],
    )
    db.add(item)
    await db.flush()
    unit = WorkItemChangeUnit(
        work_item_id=item.id,
        repository_name="service-api",
        branch_name="feature/clean-terraform",
        expected_paths_json=["terraform/base/removed.txt"],
        created_by=actor.id,
        updated_by=actor.id,
    )
    # The reviewer is the repository record's declared default reviewer (its runtime projection).
    profile = WorkRepositoryProfile(id=str(uuid.uuid4()), name="service-api", project_id=project.id,
                                    default_reviewers_json=["reviewerbb"], created_by=actor.id, updated_by=actor.id)
    unit.repository_profile_id = profile.id
    session = Session(
        user_id=actor.id,
        project_id=project.id,
        agent_type="coding",
        status="active",
        metadata_={"secure_work_execution": {"work_item_id": item.id, "change_unit_ids": [unit.id]}},
    )
    db.add_all([repo, profile, unit, session])
    await db.commit()
    return session


@pytest.mark.asyncio
async def test_create_bitbucket_pull_request_uses_registered_reviewer_profiles(db, monkeypatch, auth_user):
    project = Project(name="repo-pr-reviewer-project", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = await _seed_reviewer_change_unit_session(db, auth_user, project)

    async def fake_get(*args, **kwargs):
        return {"values": []}

    post_calls: list[dict] = []

    async def fake_post(_context, _path, *, payload):
        post_calls.append(payload)
        return {
            "id": 77,
            "title": payload["title"],
            "state": "OPEN",
            "fromRef": {"displayId": "feature/clean-terraform"},
            "toRef": {"displayId": "master"},
            "reviewers": [{"user": {"displayName": "Review Expert"}, "approved": False}],
            "links": {"self": [{"href": "https://bitbucket.example/projects/PROJ/repos/service-api/pull-requests/77"}]},
        }, 201

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_post", fake_post)

    context = _bitbucket_tool_context(db, project.id, user_id=auth_user.id, roles=["admin"], session_id=session.id)

    result = await CreateBitbucketPullRequest().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "title": "ACME-615 clean Terraform leftovers",
            "from_branch": "feature/clean-terraform",
            "to_branch": "master",
        },
        context,
    )

    assert result["status"] == "created"
    assert post_calls[0]["reviewers"] == [{"user": {"name": "reviewerbb"}}]
    assert result["delivery_contract"]["reviewer_source"] == "repository_record"
    assert result["delivery_contract"]["reviewers"] == ["reviewerbb"]
    assert result["source_control"]["operation"] == "create_change_request"
    assert result["source_control"]["repository_operation"] == "pr"
    assert result["source_control"]["evidence"]["reviewer_count"] == 1
    source_control_payload = str(
        {"output": result["source_control"]["output"], "evidence": result["source_control"]["evidence"]}
    ).lower()
    assert "secret" not in source_control_payload


def _existing_source_branch_prs() -> dict:
    return {
        "values": [
            {
                "id": 42,
                "title": "Existing PR",
                "state": "OPEN",
                "fromRef": {"displayId": "feature/existing"},
                "toRef": {"displayId": "master"},
                "links": {"self": [{"href": "https://bitbucket.example/projects/PROJ/repos/service-api/pull-requests/42"}]},
            }
        ]
    }


@pytest.mark.asyncio
async def test_create_bitbucket_pull_request_detects_existing_source_branch_pr(db, monkeypatch):
    project = Project(name="repo-pr-dedupe-project", config={}, is_active=True)
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
        return _existing_source_branch_prs()

    post_calls: list[dict] = []

    async def fake_post(*args, **kwargs):
        post_calls.append({"args": args, "kwargs": kwargs})
        return {}, 201

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_pull_requests._bitbucket_json_post", fake_post)

    context = _bitbucket_tool_context(db, project.id, user_id="user-1", roles=["admin"], session_id="session-1")

    result = await CreateBitbucketPullRequest().execute(
        {
            "project_key": "PROJ",
            "repo_slug": "service-api",
            "title": "Create duplicate",
            "from_branch": "feature/existing",
            "to_branch": "master",
        },
        context,
    )

    assert result["status"] == "existing"
    assert result["delivery_contract"]["deduplicated"] is True
    assert result["source_control"]["operation"] == "create_change_request"
    assert result["source_control"]["status"] == "existing"
    assert post_calls == []
