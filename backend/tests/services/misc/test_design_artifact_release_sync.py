"""Release and checkpoint traceability sync creates matching trace links."""

import pytest
from sqlalchemy import select

import app.services.design_delivery_sync.service as sync_service
from app.models import Project, User
from app.services.admin.task._admin_task_management import create_task
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from app.services.design_artifact.crud import create_design_artifact, create_design_trace_link
from app.services.design_delivery_sync import sync_checkpoint_traceability, sync_release_traceability


@pytest.mark.asyncio
async def test_sync_release_traceability_creates_matching_links(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    artifact = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Checkout validation",
            "status": "approved",
            "summary": "Implement checkout validation",
            "content_markdown": "## Scope",
            "is_required": True,
        },
    )
    task = await create_task(
        db,
        user_id=admin_user.id,
        payload={"project_id": project.id, "name": "Implement checkout validation", "dispatch_binding": "task_definition"},
    )
    await create_design_trace_link(
        db,
        project_id=project.id,
        payload={
            "artifact_id": artifact["id"],
            "target_type": "task",
            "target_id": task["id"],
            "title": "Implementation task",
            "status": "active",
        },
    )
    await create_design_trace_link(
        db,
        project_id=project.id,
        payload={
            "artifact_id": artifact["id"],
            "target_type": "pull_request",
            "target_id": "github#42",
            "title": "Implement checkout validation",
            "status": "completed",
            "url": "https://github.com/example/demo-github-repo/pull/42",
            "metadata_json": {
                "provider": "github",
                "repository_name": "example/demo-github-repo",
                "number": 42,
            },
        },
    )
    await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "demo-github-repo",
            "repo_root": "/tmp/demo-github-repo",
            "provider": "github",
            "remote_url": "https://github.com/example/demo-github-repo.git",
            "default_branch": "main",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "disabled",
            "is_active": True,
        },
    )

    async def fake_fetch_github_releases(db, *, owner, repo, limit):
        return [
            {
                "external_id": "github-release#100",
                "title": "Release 1.2.0",
                "body": "Includes #42 and checkout validation improvements.",
                "url": "https://github.com/example/demo-github-repo/releases/tag/v1.2.0",
                "state": "completed",
                "tag_name": "v1.2.0",
                "provider": "github",
                "repository_name": f"{owner}/{repo}",
                "object_kind": "release",
                "number": 100,
            }
        ]

    monkeypatch.setattr(sync_service, "fetch_github_releases", fake_fetch_github_releases)

    result = await sync_release_traceability(db, project_id=project.id, limit_per_repository=20)
    assert result["created_count"] == 1
    assert result["created_links"][0]["target_type"] == "release"
    assert result["created_links"][0]["target_id"] == "github-release#100"


@pytest.mark.asyncio
async def test_sync_checkpoint_traceability_creates_matching_links(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    artifact = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Checkout validation",
            "status": "approved",
            "summary": "Implement checkout validation",
            "content_markdown": "## Scope",
            "is_required": True,
        },
    )
    await create_design_trace_link(
        db,
        project_id=project.id,
        payload={
            "artifact_id": artifact["id"],
            "target_type": "pull_request",
            "target_id": "github#42",
            "title": "Implement checkout validation",
            "status": "completed",
            "metadata_json": {"provider": "github", "repository_name": "example/demo-github-repo", "number": 42},
        },
    )
    await create_design_trace_link(
        db,
        project_id=project.id,
        payload={
            "artifact_id": artifact["id"],
            "target_type": "release",
            "target_id": "github-release#100",
            "title": "Release 1.2.0",
            "status": "completed",
            "metadata_json": {
                "provider": "github",
                "repository_name": "example/demo-github-repo",
                "tag_name": "v1.2.0",
            },
        },
    )
    await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "demo-github-repo",
            "repo_root": "/tmp/demo-github-repo",
            "provider": "github",
            "remote_url": "https://github.com/example/demo-github-repo.git",
            "default_branch": "main",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "disabled",
            "is_active": True,
        },
    )

    async def fake_fetch_github_checkpoints(db, *, owner, repo, limit):
        return [
            {
                "external_id": "github-workflow#501",
                "title": "Deploy production",
                "body": "Includes #42 and release v1.2.0",
                "url": "https://github.com/example/demo-github-repo/actions/runs/501",
                "state": "completed",
                "provider": "github",
                "repository_name": f"{owner}/{repo}",
                "object_kind": "workflow_run",
                "number": 501,
                "branch": "main",
                "head_sha": "abc123",
                "event": "push",
                "conclusion": "success",
            }
        ]

    monkeypatch.setattr(sync_service, "fetch_github_checkpoints", fake_fetch_github_checkpoints)

    result = await sync_checkpoint_traceability(db, project_id=project.id, limit_per_repository=20)
    assert result["created_count"] == 1
    assert result["created_links"][0]["target_type"] == "checkpoint"
    assert result["created_links"][0]["target_id"] == "github-workflow#501"
