"""Runtime audit P-7: a Workspace cost-cap override can go back to "inherit", and a save changes only what it names."""

import uuid

import pytest

from app.models import Project
from tests.conftest import ADMIN_PASSWORD

SESSION = "agent_session_cost_limit_usd"
REQUEST = "agent_request_cost_limit_usd"


async def _workspace(client, db) -> str:
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    project = Project(id=str(uuid.uuid4()), name="cost-cap-inherit", config={}, is_active=True)
    db.add(project)
    await db.commit()
    return project.id


async def _put(client, project_id: str, body: dict):
    suffix = f"?project_id={project_id}" if project_id else ""
    return await client.put(f"/admin/chat/api/panel/runtime-settings{suffix}", json=body)


@pytest.mark.asyncio
async def test_an_override_goes_back_to_inherit_and_other_caps_stay(client, db):
    project_id = await _workspace(client, db)
    assert (await _put(client, project_id, {SESSION: 2, REQUEST: 0.5})).status_code == 200

    # Saving one cap leaves the other override in place (no silent reset to inherit).
    response = await _put(client, project_id, {SESSION: 3})
    assert response.status_code == 200
    scope = response.json()["cost_limit_scope"]
    assert scope["project_session_cost_limit_usd"] == 3
    assert scope["project_request_cost_limit_usd"] == 0.5

    response = await _put(client, project_id, {"inherit_cost_limits": [REQUEST]})
    assert response.status_code == 200
    scope = response.json()["cost_limit_scope"]
    assert scope["request_source"] == "global"
    assert scope["project_request_cost_limit_usd"] is None
    assert scope["session_source"] == "project"
    assert scope["project_session_cost_limit_usd"] == 3


@pytest.mark.asyncio
async def test_zero_stays_an_explicit_no_limit_override(client, db):
    project_id = await _workspace(client, db)
    response = await _put(client, project_id, {SESSION: 0})
    assert response.status_code == 200
    scope = response.json()["cost_limit_scope"]
    assert scope["session_source"] == "project"
    assert scope["project_session_cost_limit_usd"] == 0


@pytest.mark.asyncio
async def test_inherit_is_refused_when_ambiguous_or_out_of_scope(client, db):
    project_id = await _workspace(client, db)
    both = await _put(client, project_id, {SESSION: 1, "inherit_cost_limits": [SESSION]})
    assert both.status_code == 400
    assert "set and inherited" in both.json()["detail"]
    unknown = await _put(client, project_id, {"inherit_cost_limits": ["agent_daily_cost_limit_usd"]})
    assert unknown.status_code == 422
    # The platform value has nothing to inherit from.
    platform = await _put(client, "", {"inherit_cost_limits": [SESSION]})
    assert platform.status_code == 400
    assert "Workspace scope" in platform.json()["detail"]
