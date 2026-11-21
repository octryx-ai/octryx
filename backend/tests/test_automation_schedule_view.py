"""Schedules in words with last/next run, Action-set schedules and Work-intake rows read-only, what starts an
Action, and no silent first-Workspace fallback."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, Task, TaskRun, User
from app.models.project.scheduler import Scheduler
from app.services.admin.provider.admin_scheduler_service import list_schedulers
from app.services.admin.task._admin_task_management import create_task, list_tasks
from app.services.automation_schedule_view import schedule_in_words


def test_common_schedules_read_as_words():
    assert schedule_in_words("*/15 * * * *") == "Every 15 minutes"
    assert schedule_in_words("0 8 * * mon-fri") == "Weekdays at 08:00"
    assert schedule_in_words("0 8 * * 0-4") == "Weekdays at 08:00", "APScheduler counts Monday = 0"
    assert schedule_in_words("30 7 1 * *") == "Day 1 of every month at 07:30"
    assert schedule_in_words("0 2 * * *") == "Every day at 02:00"
    assert schedule_in_words("5 4 1-7 * 1") == "Custom: 5 4 1-7 * 1"


@pytest.mark.asyncio
async def test_schedulers_and_actions_in_words(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"sched-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    action = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Morning digest", task_type="agent_run",
                  owner_id=admin.id, is_active=True, config={"prompt": "Summarise"})
    intake = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Intake sync", task_type="secure_work_jira_sync",
                  owner_id=admin.id, is_active=True, config={})
    action_scheduled = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Old cron", task_type="agent_run",
                  owner_id=admin.id, is_active=True, schedule="0 2 * * *", config={"prompt": "x"})
    db.add_all([action, intake, action_scheduled])
    await db.flush()
    db.add_all([
        Scheduler(name="Weekday digest", cron_expression="0 8 * * mon-fri", task_id=action.id, is_active=True,
                  owner_id=admin.id),
        Scheduler(name="Intake", cron_expression="*/15 * * * *", task_id=intake.id, is_active=False, owner_id=admin.id),
        TaskRun(id=str(uuid.uuid4()), task_id=action.id, status="success", started_by=admin.id),
    ])
    await db.commit()

    rows = {row["name"]: row for row in await list_schedulers(db)}
    digest = rows["Weekday digest"]
    assert (digest["schedule_words"], digest["workspace_name"], digest["read_only"]) == (
        "Weekdays at 08:00", project.name, False)
    assert digest["last_run"]["status"] == "success" and digest["next_run"]
    assert (rows["Intake"]["managed_by_work"], rows["Intake"]["read_only"], rows["Intake"]["next_run"]) == (
        True, True, None)
    assert (rows["Old cron"]["kind"], rows["Old cron"]["read_only"]) == ("action_schedule", True)

    actions = {row["name"]: row for row in await list_tasks(db)}
    assert actions["Morning digest"]["started_by"] == [
        {"kind": "scheduler", "name": "Weekday digest", "when": "Weekdays at 08:00", "active": "yes"}]
    assert actions["Intake sync"]["managed_by_work"] is True


@pytest.mark.asyncio
async def test_an_action_without_a_workspace_is_refused(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    with pytest.raises(HTTPException) as refused:
        await create_task(db, user_id=admin.id, payload={"name": "No workspace", "agent_type": "diagnosis"})
    assert refused.value.status_code == 422
    detail = refused.value.detail
    assert (detail["state"], detail["code"], detail["reason"]) == (
        "needs_configuration", "workspace_required", "workspace_required")
