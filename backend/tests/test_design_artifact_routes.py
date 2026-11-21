"""The admin project design artifact routes."""

import pytest
from sqlalchemy import select

import app.services.design_delivery_sync.service as sync_service
from app.models import Project, TaskRun, User
from app.services.admin.project.admin_project_quality_overview import list_projects_for_quality_config
from app.services.admin.task._admin_task_management import create_task
from app.services.code_intelligence.repository import (
    create_code_repository,
)
from app.services.design_artifact.crud import update_design_artifact
from app.time_utils import utc_now
from tests.conftest import ADMIN_PASSWORD


async def _fake_fetch_github_releases(db, *, owner, repo, limit):
    return [
        {
            "external_id": "github-release#9",
            "title": "Release 1.0.0",
            "body": "Contains #88 and Checkout DoD work.",
            "url": "https://github.com/example/demo/releases/tag/v1.0.0",
            "state": "completed",
            "tag_name": "v1.0.0",
            "provider": "github",
            "repository_name": f"{owner}/{repo}",
            "object_kind": "release",
            "number": 9,
        }
    ]


async def _fake_fetch_github_checkpoints(db, *, owner, repo, limit):
    return [
        {
            "external_id": "github-workflow#777",
            "title": "Deploy checkout",
            "body": "Contains #88 and release v1.0.0",
            "url": "https://github.com/example/demo/actions/runs/777",
            "state": "completed",
            "provider": "github",
            "repository_name": f"{owner}/{repo}",
            "object_kind": "workflow_run",
            "number": 777,
            "branch": "main",
            "head_sha": "def456",
            "event": "push",
            "conclusion": "success",
        }
    ]


async def _create_dod_artifact(client, project) -> dict:
    """Creates the definition-of-done artifact and checks it is listed, scored and bootstrappable."""
    create_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-artifacts",
        json={
            "artifact_kind": "definition_of_done",
            "title": "Checkout DoD",
            "status": "draft",
            "summary": "Tests, CI, observability and rollback are mandatory.",
            "content_markdown": "- tests green\n- CI green\n- dashboards ready",
            "is_required": True,
            "order_index": 70,
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()

    list_resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/design-artifacts")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["items"][0]["id"] == created["id"]
    assert any(item["artifact_kind"] == "definition_of_done" for item in payload["templates"])

    readiness_resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/design-readiness")
    assert readiness_resp.status_code == 200
    assert "readiness_score" in readiness_resp.json()

    bootstrap_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-artifacts/bootstrap",
        json={"include_optional": False},
    )
    assert bootstrap_resp.status_code == 200
    assert "items" in bootstrap_resp.json()
    return created


async def _trace_task_and_create_from_artifact(client, db, project, admin_user, created) -> None:
    task = await create_task(
        db,
        user_id=admin_user.id,
        payload={"project_id": project.id, "name": "Trace delivery task", "dispatch_binding": "task_definition"},
    )
    trace_create_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-links",
        json={
            "artifact_id": created["id"],
            "target_type": "task",
            "target_id": task["id"],
            "title": "Task trace",
            "status": "active",
        },
    )
    assert trace_create_resp.status_code == 200
    created_trace = trace_create_resp.json()

    trace_summary_resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/design-traceability")
    assert trace_summary_resp.status_code == 200
    trace_summary = trace_summary_resp.json()
    assert trace_summary["total_links"] >= 1

    trace_delete_resp = await client.delete(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-links/{created_trace['id']}"
    )
    assert trace_delete_resp.status_code == 200

    create_task_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-artifacts/{created['id']}/create-task",
        json={"agent_type": "coding", "dispatch_binding": "task_definition"},
    )
    assert create_task_resp.status_code == 200
    task_payload = create_task_resp.json()
    assert task_payload["task"]["id"]
    assert task_payload["trace_link"]["target_type"] == "task"
    await update_design_artifact(
        db,
        artifact_id=created["id"],
        payload={"status": "approved"},
    )


def _stub_github_sync(monkeypatch) -> None:
    monkeypatch.setattr(sync_service, "fetch_github_releases", _fake_fetch_github_releases)
    monkeypatch.setattr(sync_service, "fetch_github_checkpoints", _fake_fetch_github_checkpoints)


async def _add_github_repository_and_sync_workflows(client, db, project) -> None:
    repo = await create_code_repository(
        db,
        {
            "project_id": project.id,
            "name": "demo-gh-repo",
            "repo_root": "/tmp/demo-gh-repo",
            "provider": "github",
            "remote_url": "https://github.com/example/demo-gh-repo.git",
            "default_branch": "main",
            "index_backend": "ripgrep",
            "semantic_backend": "regex",
            "structure_backend": "regex",
            "graph_backend": "disabled",
            "is_active": True,
        },
    )
    assert repo["id"]

    workflow_list_resp = await client.get(f"/admin/chat/api/panel/projects/{project.id}/design-trace-sync-workflows")
    assert workflow_list_resp.status_code == 200
    workflow_list_payload = workflow_list_resp.json()
    assert {item["id"] for item in workflow_list_payload["items"]} == {"releases", "checkpoints"}  # no PR sync

    workflow_update_resp = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-sync-workflows",
        json={
            "workflows": [
                {"id": "releases", "mode": "auto_link", "is_active": True, "limit_per_repository": 7},
                {"id": "checkpoints", "mode": "auto_link", "is_active": True, "limit_per_repository": 10},
            ]
        },
    )
    assert workflow_update_resp.status_code == 200
    assert any(
        item["id"] == "releases" and item["limit_per_repository"] == 7 for item in workflow_update_resp.json()["items"]
    )


async def _run_trace_syncs(client, project) -> None:
    removed = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-traceability/sync-pull-requests",
        json={"limit_per_repository": 10},
    )
    assert removed.status_code == 404  # pull requests are not synced into design traceability
    no_pr_workflow = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-sync-workflows/pull_requests/run", json={})
    assert no_pr_workflow.status_code in (400, 404)

    release_sync_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-traceability/sync-releases",
        json={"limit_per_repository": 10},
    )
    assert release_sync_resp.status_code == 200
    assert release_sync_resp.json()["created_count"] >= 1

    checkpoint_sync_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-traceability/sync-checkpoints",
        json={"limit_per_repository": 10},
    )
    assert checkpoint_sync_resp.status_code == 200
    assert checkpoint_sync_resp.json()["created_count"] >= 1

    generic_run_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-sync-workflows/releases/run",
        json={"limit_per_repository": 10},
    )
    assert generic_run_resp.status_code == 200
    assert generic_run_resp.json()["workflow_id"] == "releases"


async def _schedule_release_trace_sync(client, db, project) -> dict:
    schedule_resp = await client.post(
        f"/admin/chat/api/panel/projects/{project.id}/design-trace-sync-workflows/releases/create-task",
        json={
            "task_name": "Scheduled Release Trace Sync",
            "cron_expression": "0 * * * *",
            "limit_per_repository": 9,
            "is_active": True,
        },
    )
    assert schedule_resp.status_code == 200
    scheduled_payload = schedule_resp.json()
    assert scheduled_payload["task"]["name"] == "Scheduled Release Trace Sync"
    assert scheduled_payload["scheduler"]["cron_expression"] == "0 * * * *"
    refreshed_projects = await list_projects_for_quality_config(db)
    refreshed_project = next(item for item in refreshed_projects if item["id"] == project.id)
    assert any(item["id"] == scheduled_payload["task"]["id"] for item in refreshed_project["design_trace_sync_tasks"])
    assert any(
        item["id"] == scheduled_payload["scheduler"]["id"] for item in refreshed_project["design_trace_sync_schedulers"]
    )
    return scheduled_payload


async def _assert_scheduled_run_listed(db, project, admin_user, scheduled_payload) -> None:
    run = TaskRun(
        task_id=scheduled_payload["task"]["id"],
        session_id=None,
        status="completed",
        started_by=admin_user.id,
        started_at=utc_now(),
        completed_at=utc_now(),
        output={"status": "ok"},
    )
    db.add(run)
    await db.commit()
    refreshed_projects = await list_projects_for_quality_config(db)
    refreshed_project = next(item for item in refreshed_projects if item["id"] == project.id)
    trace_task = next(
        item for item in refreshed_project["design_trace_sync_tasks"] if item["id"] == scheduled_payload["task"]["id"]
    )
    assert len(trace_task["recent_runs"]) >= 1
    assert trace_task["recent_runs"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_admin_project_design_artifact_routes(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303
    project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    created = await _create_dod_artifact(client, project)
    await _trace_task_and_create_from_artifact(client, db, project, admin_user, created)
    _stub_github_sync(monkeypatch)
    await _add_github_repository_and_sync_workflows(client, db, project)
    await _run_trace_syncs(client, project)
    scheduled_payload = await _schedule_release_trace_sync(client, db, project)
    await _assert_scheduled_run_listed(db, project, admin_user, scheduled_payload)

    delete_resp = await client.delete(f"/admin/chat/api/panel/projects/{project.id}/design-artifacts/{created['id']}")
    assert delete_resp.status_code == 200
