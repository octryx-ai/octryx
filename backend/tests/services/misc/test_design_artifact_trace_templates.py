"""Custom trace sync template persistence with a GitLab source, and trace sync workflow task creation."""

import pytest
from sqlalchemy import select

import app.services.design_delivery_sync.service as sync_service
from app.models import Project, Scheduler, TaskStep, User
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from app.services.design_artifact.crud import create_design_artifact
from app.services.design_delivery_sync import (
    create_design_trace_sync_workflow_task,
    delete_project_design_trace_sync_template,
    list_project_design_trace_sync_templates,
    run_design_trace_sync_workflow,
    upsert_project_design_trace_sync_template,
)


@pytest.mark.asyncio
async def test_design_trace_sync_custom_template_persistence_and_gitlab_source(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    created = await upsert_project_design_trace_sync_template(
        db,
        project_id=project.id,
        payload={
            "id": "gitlab_release_scan",
            "name": "GitLab Release Scan",
            "source_kind": "release",
            "target_type": "release",
            "mode": "suggest",
            "providers": ["gitlab"],
            "match_rules": ["artifact_titles"],
            "limit_per_repository": 6,
            "is_active": True,
        },
    )
    assert created["id"] == "gitlab_release_scan"
    listed = await list_project_design_trace_sync_templates(db, project_id=project.id)
    assert any(item["id"] == "gitlab_release_scan" for item in listed)

    artifact = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Release 2.0.0",
            "status": "approved",
            "summary": "Ship version 2.0.0",
            "content_markdown": "## Scope",
        },
    )
    assert artifact["id"]
    await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "demo-gitlab-repo",
            "repo_root": "/tmp/demo-gitlab-repo",
            "provider": "gitlab",
            "remote_url": "https://gitlab.example.com/example/demo-gitlab-repo.git",
            "default_branch": "main",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "disabled",
            "is_active": True,
        },
    )

    async def fake_fetch_gitlab_releases(db, *, project_path, limit):
        return [
            {
                "external_id": "gitlab-release#v2.0.0",
                "title": "Release 2.0.0",
                "body": "Release notes",
                "url": "https://gitlab.example.com/example/demo-gitlab-repo/-/releases/v2.0.0",
                "state": "completed",
                "tag_name": "v2.0.0",
                "provider": "gitlab",
                "repository_name": "example/demo-gitlab-repo",
                "object_kind": "release",
                "number": "v2.0.0",
            }
        ]

    monkeypatch.setattr(sync_service, "fetch_gitlab_releases", fake_fetch_gitlab_releases)
    result = await run_design_trace_sync_workflow(db, project_id=project.id, workflow_id="gitlab_release_scan")
    assert result["workflow_id"] == "gitlab_release_scan"
    assert result["candidate_count"] == 1
    assert result["created_count"] == 0
    assert result["mode"] == "suggest"

    deleted = await delete_project_design_trace_sync_template(
        db,
        project_id=project.id,
        template_id="gitlab_release_scan",
    )
    assert deleted["status"] == "deleted"


@pytest.mark.asyncio
async def test_create_design_trace_sync_workflow_task_creates_task_steps_and_scheduler(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    created = await create_design_trace_sync_workflow_task(
        db,
        project_id=project.id,
        workflow_id="releases",
        user_id=admin_user.id,
        payload={
            "cron_expression": "0 * * * *",
            "task_name": "Trace Sync Releases",
            "scheduler_name": "Trace Sync Releases Hourly",
            "limit_per_repository": 12,
        },
    )

    assert created["task"]["name"] == "Trace Sync Releases"
    assert created["scheduler"]["cron_expression"] == "0 * * * *"
    task_steps = (
        (
            await db.execute(
                select(TaskStep).where(TaskStep.task_id == created["task"]["id"]).order_by(TaskStep.position.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(task_steps) == 2
    assert task_steps[0].connector_action == "run_design_trace_sync_workflow"
    assert task_steps[0].connector_params["workflow_id"] == "releases"
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == created["task"]["id"]))).scalar_one()
    assert scheduler.cron_expression == "0 * * * *"
