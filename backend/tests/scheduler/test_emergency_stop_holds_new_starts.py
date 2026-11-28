"""An emergency stop also holds new starts until an admin lifts it."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import KillSwitchLog, Project, Task, TaskRun, User, UserProject
from app.scheduler import TaskScheduler
from app.services.auth import create_access_token
from app.services.proactive_teams.reply_handler import process_proactive_reply

ROUTE = "/api/v1/admin/operations/emergency-stop"


def _uid() -> str:
    return str(uuid.uuid4())


async def _start(db, monkeypatch, task: Task) -> TaskRun:
    import app.db as database_module

    @asynccontextmanager
    async def same_session():
        yield db

    monkeypatch.setattr(database_module, "async_session_factory", same_session)
    await TaskScheduler()._execute_task(task.id, trigger_type="webhook")
    return (await db.execute(select(TaskRun).where(TaskRun.task_id == task.id)
                             .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one()


@pytest.mark.asyncio
async def test_a_stop_holds_new_starts_in_its_workspace_until_an_admin_resumes(client, db, monkeypatch) -> None:
    stopped_ws = Project(id=_uid(), name="Kitchen helper", is_active=True, config={})
    other_ws = Project(id=_uid(), name="Other", is_active=True, config={})
    db.add_all([stopped_ws, other_ws])
    await db.flush()
    lead = User(id=_uid(), username=f"lead-{_uid()[:8]}", email=f"{_uid()}@example.test", password_hash="!")
    db.add(lead)
    await db.flush()
    db.add(UserProject(user_id=lead.id, project_id=stopped_ws.id, role="admin"))

    def action(project: Project) -> Task:
        # A task type the scheduler refuses right after admission: enough to see whether a start was attempted.
        return Task(dispatch_binding="task_definition", id=_uid(), project_id=project.id, name="Webhook action", description="", task_type="webhook_relay",
                    owner_id=lead.id, is_active=True, config={})

    held_task, other_task = action(stopped_ws), action(other_ws)
    db.add_all([held_task, other_task])
    await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(lead.id)}"}

    stop = await client.post(ROUTE, json={"workspace_id": stopped_ws.id, "reason": "ticket storm"}, headers=headers)
    assert stop.status_code == 200 and stop.json()["new_starts_held"] is True
    preview = await client.get(f"{ROUTE}/preview", params={"workspace_id": stopped_ws.id}, headers=headers)
    assert preview.json()["new_starts_held"] is True

    held_run = await _start(db, monkeypatch, held_task)
    assert (held_run.status, held_run.output["status"]) == ("skipped", "emergency_stop")
    assert "ticket storm" in held_run.output["reason"]
    assert (await _start(db, monkeypatch, other_task)).output.get("status") != "emergency_stop"

    reply = await process_proactive_reply(db, {"ticket_id": "BRD-7", "session_id": None, "answer": "ok",
                                                "project_id": stopped_ws.id})
    assert "Automation is paused" in reply

    held = preview.json()
    assert held["held_by"] == "workspace" and held["hold"]["by"]["id"] == lead.id
    assert held["hold"]["reason"] == "ticket storm" and held["hold"]["at"]  # the person's words, no prefix

    no_reason = await client.post(f"{ROUTE}/resume", json={"workspace_id": stopped_ws.id, "reason": " "},
                                  headers=headers)
    assert no_reason.status_code == 422 and no_reason.json()["detail"]["code"] == "reason_required"
    resumed = await client.post(f"{ROUTE}/resume", json={"workspace_id": stopped_ws.id, "reason": "storm over"},
                                headers=headers)
    assert resumed.status_code == 200 and resumed.json()["new_starts_held"] is False
    log = await db.get(KillSwitchLog, resumed.json()["log_id"])
    assert (log.action, log.reason, log.user_id) == ("safe_mode_off", "storm over", lead.id)
    assert (await _start(db, monkeypatch, held_task)).output.get("status") != "emergency_stop"
    again = await client.post(f"{ROUTE}/resume", json={"workspace_id": stopped_ws.id, "reason": "x"},
                              headers=headers)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_stopped"


@pytest.mark.asyncio
async def test_a_platform_stop_is_named_and_a_workspace_resume_cannot_lift_it(client, db, auth_user) -> None:
    workspace = Project(id=_uid(), name="Kitchen helper", is_active=True, config={})
    db.add(workspace)
    await db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(auth_user.id)}"}

    stop = await client.post(ROUTE, json={"reason": "platform incident"}, headers=headers)
    assert stop.status_code == 200
    preview = (await client.get(f"{ROUTE}/preview", params={"workspace_id": workspace.id}, headers=headers)).json()
    assert preview["held_by"] == "platform" and preview["hold"]["workspace_id"] is None
    assert preview["new_starts_held"] is True

    workspace_resume = await client.post(f"{ROUTE}/resume", json={"workspace_id": workspace.id, "reason": "x"},
                                         headers=headers)
    assert workspace_resume.status_code == 409
    platform_resume = await client.post(f"{ROUTE}/resume", json={"reason": "incident closed"}, headers=headers)
    assert platform_resume.status_code == 200
    after = (await client.get(f"{ROUTE}/preview", params={"workspace_id": workspace.id}, headers=headers)).json()
    assert (after["held_by"], after["hold"], after["new_starts_held"]) == (None, None, False)
