from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob
from app.services.agent_gateway.engine_policy import set_person_choice, set_workspace_engines
from tests.devices.test_agent_runtime_pool import _runner, _runners_on  # noqa: F401


async def _codex_runner(client, db):
    runner, project = await _runner(client, db)
    runner.engines = ["codex"]  # what the product's runner image reports
    await db.commit()
    return runner, project


async def _send(client, auth_headers, project):
    return await client.post("/chat/api/send", headers=auth_headers, json={"prompt": "Hello", "project_id": project.id})


@pytest.mark.asyncio
async def test_without_a_chosen_engine_a_pool_turn_runs_on_the_runners_engine(client, db, auth_headers):
    runner, project = await _codex_runner(client, db)
    response = await _send(client, auth_headers, project)
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    assert (job.device_id, job.engine) == (runner.id, "codex")


@pytest.mark.asyncio
async def test_a_workspaces_chosen_engine_the_runner_lacks_is_still_refused(client, db, auth_headers, auth_user):
    _runner_device, project = await _codex_runner(client, db)
    await set_workspace_engines(db, project=project, value={"allowed": ["claude_code", "codex"],
                                                            "default": "claude_code"}, actor_id=auth_user.id)
    await db.commit()
    response = await _send(client, auth_headers, project)
    assert "device_engine_missing" in response.text
    assert (await db.execute(select(DeviceJob))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_persons_chosen_engine_the_runner_lacks_is_still_refused(client, db, auth_headers, auth_user):
    _runner_device, project = await _codex_runner(client, db)
    await set_person_choice(db, user_id=auth_user.id, engine="claude_code")
    await db.commit()
    response = await _send(client, auth_headers, project)
    assert "device_engine_missing" in response.text
