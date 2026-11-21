"""The agent panel's create, save and reload keep the tool surface, and unknown values or No tools with tool-using steps are refused without storing anything."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from app.models import AgentDefinition
from tests.conftest import ADMIN_PASSWORD

_AGENTS = "/admin/chat/api/panel/agents"


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _create(client, **fields) -> dict:
    body = {"name": f"Surface {uuid.uuid4().hex[:6]}", "agent_type": "diagnosis", "thinking_level": "light", **fields}
    response = await client.post(_AGENTS, json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _reload(client, agent_id: str) -> dict:
    response = await client.get(_AGENTS)
    assert response.status_code == 200
    return next(agent for agent in response.json() if agent["id"] == agent_id)


# --- panel ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_panel_create_save_and_reload_keep_both_values(client):
    await _login(client)
    governed = await _create(client)
    text_only = await _create(client, tool_surface="none")

    assert governed["toolSurface"] == "governed"
    assert (await _reload(client, governed["id"]))["toolSurface"] == "governed"
    assert (await _reload(client, text_only["id"]))["toolSurface"] == "none"

    # An unrelated save without the field keeps the stored value.
    unrelated = await client.put(f"{_AGENTS}/{text_only['id']}", json={"name": "Renamed", "goal": "New goal"})
    assert unrelated.status_code == 200, unrelated.text
    assert (await _reload(client, text_only["id"]))["toolSurface"] == "none"

    switched = await client.put(f"{_AGENTS}/{text_only['id']}", json={"name": "Renamed", "tool_surface": "governed"})
    assert switched.status_code == 200
    assert (await _reload(client, text_only["id"]))["toolSurface"] == "governed"


@pytest.mark.asyncio
async def test_panel_refuses_unknown_values_without_storing_anything(client):
    await _login(client)
    agent = await _create(client, tool_surface="none")

    assert (await client.post(_AGENTS, json={"name": "Bad", "tool_surface": "text"})).status_code == 422
    for body in ({"name": "Bad", "tool_surface": "off"}, {"name": "Bad", "tool_surface": None}):
        assert (await client.put(f"{_AGENTS}/{agent['id']}", json=body)).status_code == 422
    reloaded = await _reload(client, agent["id"])
    assert (reloaded["toolSurface"], reloaded["name"]) == ("none", agent["name"])


@pytest.mark.asyncio
async def test_panel_refuses_no_tools_with_tool_using_steps_and_never_edits_steps(client):
    await _login(client)
    governed = await _create(client)
    step = await client.post(
        f"{_AGENTS}/{governed['id']}/steps",
        json={"name": "Search docs", "allowed_tools": ["knowledge_search"], "is_enabled": True},
    )
    assert step.status_code == 200

    refused = await client.put(f"{_AGENTS}/{governed['id']}", json={"name": "Changed", "tool_surface": "none"})
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("No tools (text only) conflicts with steps that use tools: Search docs")
    reloaded = await _reload(client, governed["id"])
    assert (reloaded["toolSurface"], reloaded["name"]) == ("governed", governed["name"])
    assert reloaded["steps"][0]["allowedTools"] == ["knowledge_search"]

    text_only = await _create(client, tool_surface="none")
    tool_step = await client.post(
        f"{_AGENTS}/{text_only['id']}/steps", json={"name": "Search", "allowed_tools": ["web_search"]}
    )
    required_step = await client.post(
        f"{_AGENTS}/{text_only['id']}/steps", json={"name": "Must call", "step_config": {"tool_use": "required"}}
    )
    text_step = await client.post(
        f"{_AGENTS}/{text_only['id']}/steps", json={"name": "Answer", "step_config": {"tool_use": "optional"}}
    )
    assert (tool_step.status_code, required_step.status_code, text_step.status_code) == (409, 409, 200)
    step_id = text_step.json()["id"]
    edited = await client.put(
        f"{_AGENTS}/{text_only['id']}/steps/{step_id}", json={"name": "Answer", "allowed_tools": ["web_search"]}
    )
    assert edited.status_code == 409
    assert (await _reload(client, text_only["id"]))["steps"][0]["allowedTools"] == []


@pytest.mark.asyncio
async def test_an_unrelated_panel_save_never_keeps_or_widens_a_stored_invalid_value(client, db):
    await _login(client)
    agent = await _create(client)
    await db.execute(update(AgentDefinition).where(AgentDefinition.id == agent["id"]).values(tool_surface=""))
    await db.commit()

    assert (await _reload(client, agent["id"]))["toolSurface"] == ""
    unrelated = await client.put(f"{_AGENTS}/{agent['id']}", json={"name": "Renamed"})
    assert unrelated.status_code == 422
    reloaded = await _reload(client, agent["id"])
    assert (reloaded["toolSurface"], reloaded["name"]) == ("", agent["name"])

    chosen = await client.put(f"{_AGENTS}/{agent['id']}", json={"name": "Renamed", "tool_surface": "none"})
    assert chosen.status_code == 200
    assert (await _reload(client, agent["id"]))["toolSurface"] == "none"
