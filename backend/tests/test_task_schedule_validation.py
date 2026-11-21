"""Task.schedule authoring validation.

Every writer of ``Task.schedule`` refuses a value the scheduler cannot register or that never fires,
before it writes anything. Each writer keeps its own removal contract, and valid values
are stored byte-identical (no cron, weekday or time zone reinterpretation).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models import Task
from app.scheduler.dispatch.cron_schedule import require_schedulable_cron
from app.services.admin.task import _admin_task_management as admin_tasks
from app.services.task_schedule_authoring import require_task_schedule
from tests.action_agent_binding_support import bound_action_fields
from tests.task_schedule_validation_support import _admin, _detail, _project, _task_count

RARE_VALID = ["0 9 * * 0", "0 0 29 2 *", "*/15 * * * mon-fri", "5 4 1,15 * 6"]


REFUSED = [
    ("61 * * * *", "cron_field_invalid"),
    ("0 9 * * 7", "cron_field_invalid"),  # APScheduler weekdays are 0-6 (Monday = 0)
    ("* * * *", "cron_field_count"),
    ("0 0 31 4 *", "cron_never_fires"),
    ("   ", "cron_required"),
    ("* " * 60, "cron_too_long"),
]


NON_TEXT = [0, 5, False, True, [], {}, ["0 9 * * *"]]


# --- helper contract -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "code"), REFUSED)
async def test_unschedulable_values_are_refused_with_the_schedule_field(value, code):
    with pytest.raises(HTTPException) as exc:
        await require_task_schedule(value)
    detail = _detail(exc)
    assert (detail["code"], detail["field"]) == (code, "schedule")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", NON_TEXT)
async def test_raw_non_text_is_refused_never_coerced_to_removal(value):
    with pytest.raises(HTTPException) as exc:
        await require_task_schedule(value)
    assert _detail(exc)["code"] == "schedule_not_text"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", *RARE_VALID])
async def test_removal_and_rare_valid_values_pass(value):
    await require_task_schedule(value)


@pytest.mark.asyncio
async def test_scheduler_consumers_keep_the_cron_expression_field():
    with pytest.raises(HTTPException) as exc:
        await require_schedulable_cron("61 * * * *")
    assert _detail(exc)["field"] == "cron_expression"


# --- admin panel ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_panel_create_refuses_before_writing_and_stores_valid_values_verbatim(client, auth_headers, db):
    project = await _project(db)
    bound = await bound_action_fields(db, project.id)
    for value, code in REFUSED[:4]:
        resp = await client.post(
            "/admin/chat/api/panel/tasks",
            json={"name": "w1-refused", "agent_type": "diagnosis", "schedule": value, "project_id": project.id,
                  **bound},
            headers=auth_headers,
        )
        assert resp.status_code == 422, value
        assert resp.json()["detail"]["code"] == code
    assert await _task_count(db, "w1-refused") == 0

    for index, (value, stored) in enumerate([*[(v, v) for v in RARE_VALID], (None, None), ("", None)]):
        resp = await client.post(
            "/admin/chat/api/panel/tasks",
            json={"name": f"w1-ok-{index}", "agent_type": "diagnosis", "schedule": value, "project_id": project.id,
                  **bound},
            headers=auth_headers,
        )
        assert resp.status_code == 200, (value, resp.text)
        assert resp.json()["schedule"] == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, 0, [], {}])
async def test_untyped_admin_create_callers_cannot_coerce_a_non_string(db, value):
    admin = await _admin(db)
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.create_task(
            db, user_id=admin.id, payload={"name": "w1a-untyped", "agent_type": "diagnosis", "schedule": value,
                                          "project_id": (await _project(db)).id}
        )
    assert _detail(exc)["code"] == "schedule_not_text"
    assert await _task_count(db, "w1a-untyped") == 0


@pytest.mark.asyncio
async def test_panel_update_transport_omission_null_empty_and_refusal(client, auth_headers, db):
    project = await _project(db)
    created = await client.post(
        "/admin/chat/api/panel/tasks",
        json={"name": "w2-task", "agent_type": "diagnosis", "schedule": "0 9 * * 0", "project_id": project.id,
              **await bound_action_fields(db, project.id)},
        headers=auth_headers,
    )
    task_id = created.json()["id"]
    url = f"/admin/chat/api/panel/tasks/{task_id}"

    async def stored() -> str | None:
        task = await db.get(Task, task_id)
        await db.refresh(task)
        return task.schedule

    # Omission keeps the stored value on an unrelated edit.
    assert (await client.put(url, json={"name": "w2-renamed"}, headers=auth_headers)).status_code == 200
    assert await stored() == "0 9 * * 0"
    # A refused value changes nothing, not even the other submitted fields.
    refused = await client.put(url, json={"name": "w2-not-applied", "schedule": "0 0 31 4 *"}, headers=auth_headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "cron_never_fires"
    assert (await db.get(Task, task_id)).name == "w2-renamed"
    assert await stored() == "0 9 * * 0"
    # "" keeps its stored form; explicit null clears, as the task form intends.
    assert (await client.put(url, json={"schedule": ""}, headers=auth_headers)).status_code == 200
    assert await stored() == ""
    assert (await client.put(url, json={"schedule": "*/15 * * * mon-fri"}, headers=auth_headers)).status_code == 200
    assert await stored() == "*/15 * * * mon-fri"
    assert (await client.put(url, json={"schedule": None}, headers=auth_headers)).status_code == 200
    assert await stored() is None
    # Other explicit nulls are still ignored.
    assert (await client.put(url, json={"description": None}, headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_panel_update_validates_a_resubmitted_stored_value(client, auth_headers, db):
    admin, project = await _admin(db), await _project(db)
    stored = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="w2-stored", agent_type="diagnosis",
                  schedule="0 9 * * 7", config={}, owner_id=admin.id)
    db.add(stored)
    await db.commit()
    url = f"/admin/chat/api/panel/tasks/{stored.id}"

    refused = await client.put(url, json={"name": "w2-renamed", "schedule": "0 9 * * 7"}, headers=auth_headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["field"] == "schedule"
    await db.refresh(stored)
    assert stored.name == "w2-stored"


@pytest.mark.asyncio
async def test_panel_task_routes_keep_their_admin_gate(client, db):
    resp = await client.post(
        "/admin/chat/api/panel/tasks", json={"name": "w1-anon", "agent_type": "diagnosis", "schedule": "61 * * * *"}
    )
    assert resp.status_code in {401, 403}
    assert await _task_count(db, "w1-anon") == 0


# --- REST --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_create_refuses_before_writing_and_keeps_its_storage(client, auth_headers, db):
    project = await _project(db)
    base = {"project_id": project.id, "agent_type": "diagnosis", "config": {}, "dispatch_binding": "task_definition"}
    refused = await client.post("/api/v1/tasks", json={**base, "name": "w3-refused", "schedule": "0 0 31 4 *"},
                                headers=auth_headers)
    assert refused.status_code == 422
    assert refused.json()["detail"]["field"] == "schedule"
    assert await _task_count(db, "w3-refused") == 0

    for index, (value, stored) in enumerate([("0 9 * * 0", "0 9 * * 0"), ("", ""), (None, None)]):
        resp = await client.post("/api/v1/tasks", json={**base, "name": f"w3-ok-{index}", "schedule": value},
                                 headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["schedule"] == stored

    anonymous = await client.post("/api/v1/tasks", json={**base, "name": "w3-anon", "schedule": "61 * * * *"})
    assert anonymous.status_code == 401
    assert await _task_count(db, "w3-anon") == 0
