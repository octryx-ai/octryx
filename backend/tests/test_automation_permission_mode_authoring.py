"""Contract: Automation targets name an active permission mode explicitly.

- admin Action (task) and Webhook create/update, and REST ``POST /api/v1/webhooks``: an explicitly
  submitted ``agent_type`` that is blank, non-text, unknown or inactive is a typed 422, before any
  row is written or changed;
- an omitted value keeps its existing default (REST/schema/service omission), and an update without
  ``agent_type`` keeps the stored value, even a legacy key that would no longer validate;
- valid keys are stored (normalized).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Project, Task
from app.services.agent_mode import normalize_agent_mode_key
from app.services.agent_mode.authoring import authored_agent_mode, authoring_key_form, require_explicit_agent_mode
from tests.action_agent_binding_support import bound_action_fields
from tests.conftest import ADMIN_PASSWORD

pytestmark = pytest.mark.asyncio
PANEL = "/admin/chat/api/panel"


async def _login_admin(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _project_id(db) -> str:
    return (await db.execute(select(Project.id))).scalars().first()


async def _inactive_mode(db) -> str:
    """Run modes are shipped code; a key outside them (e.g. a custom mode) is refused alike."""
    del db
    return f"paused_{uuid.uuid4().hex[:6]}"


async def _count(db, model) -> int:
    await db.rollback()
    return (await db.execute(select(func.count(model.id)))).scalar_one()


def _code(response) -> str:
    return response.json()["detail"]["code"]


# ---- the helper ------------------------------------------------------------------------------------


async def test_explicit_values_must_name_an_active_mode(db):
    inactive = await _inactive_mode(db)
    for value in ("", "   ", None, 7, ["diagnosis"]):
        with pytest.raises(HTTPException) as exc:
            await require_explicit_agent_mode(db, value)
        assert exc.value.status_code == 422 and exc.value.detail["code"] == "agent_mode_required", value
    for value in ("no_such_mode", inactive):
        with pytest.raises(HTTPException) as exc:
            await require_explicit_agent_mode(db, value)
        assert exc.value.status_code == 422 and exc.value.detail["code"] == "unknown_agent_mode", value
    assert await require_explicit_agent_mode(db, "Diagnosis") == "diagnosis"
    # Omission keeps the existing default resolution; presence is explicit.
    assert await authored_agent_mode(db, {}) == "diagnosis"
    with pytest.raises(HTTPException):
        await authored_agent_mode(db, {"agent_type": ""})


# ---- admin Webhook ----------------------------------------------------------------------------------


async def test_admin_task_create_and_update_validate_only_explicit_modes(client, db):
    await _login_admin(client)
    project_id, inactive = await _project_id(db), await _inactive_mode(db)
    bound = await bound_action_fields(db, project_id)
    before = await _count(db, Task)
    for value in ("", "no_such_mode", inactive):
        refused = await client.post(
            f"{PANEL}/tasks", json={"name": "action", "project_id": project_id, "agent_type": value, **bound}
        )
        assert refused.status_code == 422, (value, refused.text)
    assert await _count(db, Task) == before, "no task row written"
    created = await client.post(
        f"{PANEL}/tasks", json={"name": "action", "project_id": project_id, "agent_type": "change", **bound}
    )
    assert created.status_code == 200 and created.json()["agent_type"] == "change"
    task_id = created.json()["id"]

    await db.rollback()
    task = await db.get(Task, task_id)
    task.agent_type = "retired_mode"
    await db.commit()
    unrelated = await client.put(f"{PANEL}/tasks/{task_id}", json={"description": "kept"})
    assert unrelated.status_code == 200 and unrelated.json()["agent_type"] == "retired_mode"
    refused = await client.put(f"{PANEL}/tasks/{task_id}", json={"description": "changed", "agent_type": inactive})
    assert refused.status_code == 422 and _code(refused) == "unknown_agent_mode"
    await db.rollback()
    row = await db.get(Task, task_id)
    await db.refresh(row)
    assert (row.agent_type, row.description) == ("retired_mode", "kept")


# ---- REST POST /api/v1/webhooks ---------------------------------------------------------------------


NON_KEYS = ["!!!", "___", "_", "-", "  !! ", "__ __", "ÄÖÜ", "é", "日本語", "🙂", "--__--"]


@pytest.mark.parametrize("value", NON_KEYS)
async def test_a_value_without_key_characters_is_refused_before_the_default_fallback(db, value):
    assert normalize_agent_mode_key(value) == "diagnosis", "the global normalizer falls back (unchanged)"
    with pytest.raises(HTTPException) as exc:
        await require_explicit_agent_mode(db, value)
    assert exc.value.status_code == 422 and exc.value.detail["code"] == "invalid_agent_mode_key"


async def test_valid_normalization_is_preserved_and_matches_the_global_rule(db):
    for value, key in (
        ("Diagnosis", "diagnosis"),
        (" change ", "change"),
        ("CHANGE!", "change"),
        ("_change_", "change"),
    ):
        assert authoring_key_form(value) == normalize_agent_mode_key(value) == key
        assert await require_explicit_agent_mode(db, value) == key
    for value in ("Data Review", "a-b c", "x__y", "Mode 2"):
        assert authoring_key_form(value) == normalize_agent_mode_key(value), value


@pytest.mark.parametrize("value", ["!!!", "___", "ÄÖ"])
async def test_every_authoring_route_refuses_a_non_key_without_writing(client, db, auth_headers, value):
    # Inbound webhooks carry no run mode: they start an Action, which owns it.
    await _login_admin(client)
    project_id = await _project_id(db)
    body = {"name": "non-key probe", "project_id": project_id, "agent_type": value,
            **await bound_action_fields(db, project_id)}
    tasks = await _count(db, Task)
    response = await client.post(f"{PANEL}/tasks", json=body)
    assert response.status_code == 422 and _code(response) == "invalid_agent_mode_key", response.text
    assert await _count(db, Task) == tasks, "no target written"

    task = await client.post(f"{PANEL}/tasks", json={**body, "agent_type": "change"})
    assert task.status_code == 200
    refused = await client.put(
        f"{PANEL}/tasks/{task.json()['id']}", json={"description": "changed", "agent_type": value}
    )
    assert refused.status_code == 422 and _code(refused) == "invalid_agent_mode_key"
    await db.rollback()
    row = await db.get(Task, task.json()["id"])
    await db.refresh(row)
    assert row.agent_type == "change" and row.description != "changed", "update refused before any change"
