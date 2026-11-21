"""Design artifact CRUD and project projection, the design context tools, bootstrap and readiness, trace links and tasks from artifacts."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, User
from app.services.admin.project.admin_project_quality_overview import list_projects_for_quality_config
from app.services.admin.task._admin_task_management import create_task
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from app.services.design_artifact.crud import (
    create_design_artifact,
    create_design_trace_link,
    create_task_from_design_artifact,
    delete_design_artifact,
    delete_design_trace_link,
    list_design_artifacts,
    list_design_trace_links,
    update_design_artifact,
)
from app.services.design_artifact_service import (
    bootstrap_design_artifacts,
    get_project_design_context,
    get_project_design_readiness,
    get_project_design_traceability,
)
from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_design_tools import (
    GetProjectDesignContextTool,
    GetProjectDesignReadinessTool,
    ListProjectDesignArtifactsTool,
)


@pytest.mark.asyncio
async def test_design_artifact_crud_and_project_projection(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()

    created = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "outcome_brief",
            "title": "Checkout outcome",
            "status": "draft",
            "summary": "Reduce checkout abandonment.",
            "content_markdown": "## Goal\nReduce abandonment by 5%.",
            "is_required": True,
            "order_index": 10,
        },
    )
    assert created["artifact_kind"] == "outcome_brief"
    assert created["is_required"] is True

    updated = await update_design_artifact(
        db,
        artifact_id=created["id"],
        payload={
            "status": "approved",
            "summary": "Reduce abandonment by 5 percent.",
        },
    )
    assert updated["status"] == "approved"

    items = await list_design_artifacts(db, project_id=project.id)
    assert len(items) == 1
    assert items[0]["title"] == "Checkout outcome"

    context = await get_project_design_context(db, project_id=project.id)
    assert context["approved_count"] == 1
    assert context["coverage"]["outcome_brief"] == 1

    projects = await list_projects_for_quality_config(db)
    projected = next(item for item in projects if item["id"] == project.id)
    assert len(projected["design_artifacts"]) == 1
    assert projected["design_artifacts"][0]["status"] == "approved"

    deleted = await delete_design_artifact(db, artifact_id=created["id"])
    assert deleted["ok"] is True
    assert await list_design_artifacts(db, project_id=project.id) == []


@pytest.mark.asyncio
async def test_design_artifact_tools_read_project_context(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    created = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "acceptance_criteria",
            "title": "Checkout examples",
            "status": "review",
            "summary": "Examples for failed payment and success.",
            "content_markdown": "- success path\n- failed payment path",
            "order_index": 30,
        },
    )

    context = ToolContext(
        user_id=str(uuid.uuid4()),
        project_ids=[project.id],
        roles=["admin"],
        session_id=str(uuid.uuid4()),
        project_config={},
        db=db,
        workspace_root="/tmp",
    )

    listing = await ListProjectDesignArtifactsTool().execute({}, context)
    assert listing["count"] == 1
    assert listing["items"][0]["id"] == created["id"]

    summary = await GetProjectDesignContextTool().execute({}, context)
    assert summary["total_count"] == 1
    assert summary["coverage"]["acceptance_criteria"] == 1

    readiness = await GetProjectDesignReadinessTool().execute({}, context)
    assert "missing_required_kinds" in readiness


@pytest.mark.asyncio
async def test_design_artifact_bootstrap_and_readiness_with_repository_traceability(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    repo = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "demo-repo",
            "repo_root": "/tmp/demo-repo",
            "provider": "local",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "disabled",
            "is_active": True,
        },
    )

    seeded = await bootstrap_design_artifacts(db, project_id=project.id, include_optional=False)
    assert seeded["created_count"] >= 1
    outcome = next(item for item in seeded["items"] if item["artifact_kind"] == "outcome_brief")

    await update_design_artifact(
        db,
        artifact_id=outcome["id"],
        payload={
            "status": "approved",
            "linked_repository_ids": [repo["id"]],
        },
    )

    readiness = await get_project_design_readiness(db, project_id=project.id)
    assert readiness["required_total"] >= 1
    assert readiness["approved_required_total"] >= 1
    assert readiness["repository_traceability"]["linked_repositories"] == 1
    assert isinstance(readiness["blockers"], list)


@pytest.mark.asyncio
async def test_design_traceability_links_and_summary(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    artifact = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "prd",
            "title": "Checkout PRD",
            "status": "approved",
            "summary": "Implement checkout validation.",
            "content_markdown": "## Scope",
            "is_required": True,
            "order_index": 20,
        },
    )
    task = await create_task(
        db,
        user_id=admin_user.id,
        payload={
            "dispatch_binding": "task_definition",
            "project_id": project.id,
            "name": "Implement checkout validation",
            "description": "Delivery task",
        },
    )
    task_link = await create_design_trace_link(
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
    pr_link = await create_design_trace_link(
        db,
        project_id=project.id,
        payload={
            "artifact_id": artifact["id"],
            "target_type": "pull_request",
            "target_id": "github#42",
            "title": "Checkout PR",
            "status": "completed",
            "url": "https://example.invalid/pr/42",
        },
    )

    links = await list_design_trace_links(db, project_id=project.id, artifact_id=artifact["id"])
    assert len(links) == 2

    summary = await get_project_design_traceability(db, project_id=project.id)
    assert summary["total_links"] == 2
    assert summary["link_counts_by_type"]["task"] == 1
    assert summary["link_counts_by_type"]["pull_request"] == 1
    assert summary["approved_artifacts_linked"] >= 1

    deleted = await delete_design_trace_link(db, link_id=task_link["id"])
    assert deleted["ok"] is True
    remaining = await list_design_trace_links(db, project_id=project.id, artifact_id=artifact["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == pr_link["id"]


@pytest.mark.asyncio
async def test_create_task_from_design_artifact_creates_trace_link(db):
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    artifact = await create_design_artifact(
        db,
        project_id=project.id,
        payload={
            "artifact_kind": "acceptance_criteria",
            "title": "Checkout validation examples",
            "status": "approved",
            "summary": "Define validation edge cases",
            "content_markdown": "- invalid card\n- duplicate charge",
            "is_required": True,
            "order_index": 30,
        },
    )

    created = await create_task_from_design_artifact(
        db,
        project_id=project.id,
        artifact_id=artifact["id"],
        user_id=admin_user.id,
        payload={"dispatch_binding": "task_definition"},
    )
    assert created["task"]["name"] == "Checkout validation examples"
    assert created["task"]["dispatch_binding"] == "task_definition"
    assert created["trace_link"]["target_type"] == "task"
    assert created["trace_link"]["target_id"] == created["task"]["id"]
