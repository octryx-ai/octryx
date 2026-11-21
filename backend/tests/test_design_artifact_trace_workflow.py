"""The design trace sync workflow configuration, the generic runner and custom workflow normalization."""

import uuid

import pytest
from sqlalchemy import select

import app.services.design_delivery_sync.service as sync_service
from app.models import Project
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from app.services.design_artifact.crud import create_design_artifact
from app.services.design_delivery_sync import (
    get_project_design_trace_sync_workflows,
    normalize_design_trace_sync_workflows,
    run_design_trace_sync_workflow,
    upsert_project_design_trace_sync_template,
)
from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_design_tools import RunDesignTraceSyncWorkflowTool


def _release(external_id: str, title: str, body: str):
    async def fetch(db, *, owner, repo, limit):
        return [{"external_id": external_id, "title": title, "body": body, "state": "completed",
                 "url": f"https://github.com/{owner}/{repo}/releases/tag/v1", "tag_name": "v1", "number": 1,
                 "provider": "github", "repository_name": f"{owner}/{repo}", "object_kind": "release"}]

    return fetch


@pytest.mark.asyncio
async def test_design_trace_sync_workflow_config_and_generic_runner(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Checkout validation",
            "status": "approved",
            "summary": "Implement checkout validation",
            "content_markdown": "## Scope",
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

    monkeypatch.setattr(sync_service, "fetch_github_releases", _release("github-release#77", "Checkout validation",
                                                                         "Implements checkout validation."))

    normalized = normalize_design_trace_sync_workflows(
        [
            {
                "id": "releases",
                "mode": "suggest",
                "limit_per_repository": 12,
                "is_active": True,
            }
        ]
    )
    assert any(item["id"] == "releases" and item["mode"] == "suggest" for item in normalized)

    project.config = {"design_trace_sync_workflows": normalized}
    await db.commit()
    await db.refresh(project)

    workflows = get_project_design_trace_sync_workflows(dict(project.config or {}))
    assert any(item["id"] == "releases" and item["mode"] == "suggest" for item in workflows)

    result = await run_design_trace_sync_workflow(db, project_id=project.id, workflow_id="releases")
    assert result["workflow_id"] == "releases"
    assert result["mode"] == "suggest"
    assert result["candidate_count"] == 1
    assert result["created_count"] == 0

    context = ToolContext(
        user_id=str(uuid.uuid4()),
        project_ids=[project.id],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config=dict(project.config or {}),
        db=db,
        workspace_root="/tmp",
    )
    tool_result = await RunDesignTraceSyncWorkflowTool().execute(
        {"workflow_id": "releases"},
        context,
    )
    assert tool_result["workflow_id"] == "releases"
    assert tool_result["mode"] == "suggest"


@pytest.mark.asyncio
async def test_design_trace_sync_workflow_normalizes_custom_workflow(db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Checkout Validation",
            "status": "approved",
            "summary": "Implement checkout validation",
            "content_markdown": "## Scope",
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

    monkeypatch.setattr(sync_service, "fetch_github_releases", _release("github-release#91", "Checkout Validation",
                                                                         "No task title or tokens needed here."))

    normalized = normalize_design_trace_sync_workflows(
        [
            {
                "id": "custom_release_titles",
                "name": "Custom Release Titles",
                "source_kind": "release",
                "target_type": "release",
                "mode": "suggest",
                "providers": ["github"],
                "match_rules": ["artifact_titles"],
                "limit_per_repository": 5,
                "is_active": True,
            }
        ]
    )
    project.config = {"design_trace_sync_workflows": normalized}
    await db.commit()
    await db.refresh(project)

    workflows = get_project_design_trace_sync_workflows(dict(project.config or {}))
    assert any(item["id"] == "custom_release_titles" and item["is_template"] is False for item in workflows)
    result = await run_design_trace_sync_workflow(db, project_id=project.id, workflow_id="custom_release_titles")
    assert result["workflow_id"] == "custom_release_titles"
    assert result["candidate_count"] == 1
    assert result["match_rules"] == ["artifact_titles"]


@pytest.mark.asyncio
async def test_pull_requests_are_not_a_design_trace_sync_source(db):
    """Pull request traceability sync is cut from the alpha: no built-in workflow, no custom one, no template."""
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    workflows = normalize_design_trace_sync_workflows([
        {"id": "pull_requests", "mode": "suggest"},
        {"id": "custom_pr_scan", "source_kind": "pull_request", "target_type": "pull_request"},
    ])
    assert {item["id"] for item in workflows} == {"releases", "checkpoints"}
    with pytest.raises(ValueError, match="Unsupported trace sync source kind"):
        await upsert_project_design_trace_sync_template(
            db, project_id=project.id, payload={"id": "custom_pr_scan", "source_kind": "pull_request"})
    with pytest.raises(ValueError):
        await run_design_trace_sync_workflow(db, project_id=project.id, workflow_id="pull_requests")
