"""Jira sync configuration, the scheduled sync task and the block when the connector is missing."""

import pytest
from sqlalchemy import select

import app.services.secure_work.jira.jira_sync_source as jira_sync_source
import app.services.secure_work.jira.jira_sync_task as jira_sync_task
from app.models import Project, Scheduler, Task, TaskRun, WorkItem
from tests.jira_intake_support import create_jira_intake, run_jira_intake, update_jira_intake
from tests.secure_work_jira_sync_support import _issue


@pytest.mark.asyncio
async def test_jira_sync_config_update_persists_scheduler_and_automation_policy(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Acme Orders scheduled OCX intake",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
    })
    config_id = created["id"]

    updated = await update_jira_intake(db, config_id, {
        "is_active": True,
        "sync_options": {
            "schedule": {"preset": "custom", "cron": "*/1 * * * *"},
            "max_results": 1000,
            "automation_labels": ["octryx"],
            "automation_mode": "direct",
        },
    })
    options = updated["sync_options"]
    assert options["schedule"] == {"preset": "custom", "cron": "*/1 * * * *"}
    assert options["max_results"] == 1000
    assert options["automation_labels"] == ["octryx"]
    assert options["automation_mode"] == "direct"

    tasks = (
        await db.execute(select(Task).where(Task.task_type == "secure_work_jira_sync"))
    ).scalars().all()
    task = next(row for row in tasks if row.config["sync_config_id"] == config_id)
    assert task.is_active is True
    assert task.config["limit"] == 1000
    assert task.config["local_execution"] == "deterministic"
    assert task.config["requires_worker"] is False
    assert task.config["required_domain"] == "jira"
    scheduler = (
        await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))
    ).scalar_one()
    assert scheduler.is_active is True
    assert scheduler.cron_expression == "*/1 * * * *"

    await run_jira_intake(db, config_id, {
        "issues": [_issue("OCX-78", summary="Automate scheduled work", labels=["octryx", "acme-orders"])]})
    list_response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={config_id}&limit=1000",
        headers=auth_headers,
    )
    item = list_response.json()["items"][0]
    assert item["automation_eligibility"]["mode"] == "direct"
    assert item["automation_eligibility"]["matched_labels"] == ["octryx"]


@pytest.mark.asyncio
async def test_scheduled_jira_work_item_sync_task_executes_configured_sync(client, auth_headers, db, monkeypatch):
    async def fake_fetch(db_arg, *, config, jql, limit):
        return {
            "configured": True,
            "issues": [_issue("OCX-SCHEDULED-1", summary="Scheduled sync item", labels=["octryx"])],
            "source_count": 1,
            "source_complete": True,
            "metadata": {"source": "test_scheduler", "requested_limit": limit, "jql": jql},
        }

    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync", fake_fetch)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Scheduled Work Intake",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
        "sync_options": {
            "schedule": {"preset": "every_minute"},
            "max_results": 1000,
            "automation_labels": ["octryx"],
        },
    })
    config_id = created["id"]
    tasks = (
        await db.execute(select(Task).where(Task.task_type == "secure_work_jira_sync"))
    ).scalars().all()
    task = next(row for row in tasks if row.config["sync_config_id"] == config_id)
    task_run = TaskRun(task_id=task.id, started_by=task.owner_id, input_=task.config or {}, status="running")
    db.add(task_run)
    await db.flush()

    output = await jira_sync_task.run_scheduled_jira_work_item_sync(db, task=task, task_run=task_run)

    assert output["mode"] == "secure_work_jira_sync"
    assert output["summary"]["imported"] == 1
    assert output["summary"]["source"]["source"] == "test_scheduler"
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-SCHEDULED-1"))).scalar_one()
    assert item.source_fields_json["automation_policy"]["trigger_labels"] == ["octryx"]


@pytest.mark.asyncio
async def test_jira_sync_blocks_when_connector_is_missing(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Missing Jira connector",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
    })

    sync_run = (await run_jira_intake(db, created["id"], dry_run=True))["sync_run"]
    assert sync_run["status"] == "blocked"
    assert sync_run["summary"]["blocked"] is True
    assert "Jira connector is not configured" in sync_run["summary"]["block_reason"]
