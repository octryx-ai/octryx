"""A person's chat on a server runner without a mode chose "Ask first": the runner gets the mode by name, so Codex asks
before a change; a chosen mode stays, and a platform-driven turn (a task, a run's phase) keeps no mode."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session
from app.services.devices.agent_runtime import runner_turn
from tests.devices.test_agent_runtime_pool import _answers, _runner, _runners_on  # noqa: F401


async def _job(db) -> DeviceJob:
    return (await db.execute(select(DeviceJob).order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one()


@pytest.mark.asyncio
async def test_a_chat_message_without_a_mode_asks_first_on_the_runner(client, db, auth_headers):
    _runner_device, project = await _runner(client, db)
    response = await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Hello",
                                                                               "project_id": project.id})
    assert response.status_code == 200, response.text
    assert (await _job(db)).turn_permission_mode == "default"


@pytest.mark.asyncio
async def test_a_chosen_mode_stays_as_chosen(client, db, auth_headers):
    _runner_device, project = await _runner(client, db)
    response = await client.post("/chat/api/send", headers=auth_headers, json={
        "prompt": "Hello", "project_id": project.id,
        "execution_target": {"kind": "device", "device_id": "pool", "permission_mode": "acceptEdits"}})
    assert response.status_code == 200, response.text
    assert (await _job(db)).turn_permission_mode == "acceptEdits"


@pytest.mark.asyncio
async def test_an_api_message_asks_first_and_a_task_turn_keeps_no_mode(client, db, auth_headers, auth_user,
                                                                       monkeypatch):
    _runner_device, project = await _runner(client, db)
    thread = Session(user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", metadata_={})
    task_thread = Session(user_id=auth_user.id, project_id=project.id, agent_type="diagnosis", metadata_={})
    db.add_all([thread, task_thread])
    await db.commit()
    _answers(db, "Done.", monkeypatch)
    response = await client.post(f"/api/v1/sessions/{thread.id}/messages", headers=auth_headers,
                                 json={"content": "Hello"})
    assert response.status_code == 200, response.text
    assert (await _job(db)).turn_permission_mode == "default"

    await runner_turn(db, user_id=auth_user.id, prompt="Nightly summary", session_id=task_thread.id)
    assert (await _job(db)).turn_permission_mode in ("", None)
