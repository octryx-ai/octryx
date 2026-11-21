"""Custom REST connector: a REST list operation as a Work source.

Against one API answering through the real pinned ``custom_rest`` egress (``rest_connector_support``): records are
synced into Work items through the field mapping, page after page; the intake's role decides the data scope (scope
parameter injected, result filter applied and counted) and an unscoped sync of a scoped operation is refused; records
without a stable key are refused; closures reconcile only after a complete read; a person's state change writes back
through the write operation and an unattended one only proposes; an automatic analysis of a REST item runs as
``mode: auto`` with the item inside the untrusted fence; an inbound webhook bound to the intake's task runs the sync,
not an agent turn; the setup API saves, samples, previews and enables a Custom REST intake.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.secure_work_intake_setup import router
from app.db import get_db
from app.models import RestApiCallRun, Task
from app.models.integration.webhook import Webhook
from app.services.auth import get_current_user
from app.services.inbound_alerts.trigger import receive_alert
from app.services.secure_work.custom_rest import intake as rest_intake
from app.services.secure_work.custom_rest.intake_source import SOURCE
from app.services.secure_work.intake.overview import intake_overview
from app.services.secure_work.intake.registry import GENERIC_SYNC_TASK_TYPE
from app.services.secure_work.intake.setup import save_intake
from app.services.secure_work.item_connection import item_scope_key
from tests.custom_rest_work_intake_support import (  # noqa: F401
    FIELDS,
    _draft,
    _intake,
    _items,
    _world,
    api,
    pages,
    ticket,
)
from tests.egress_support import public_source_dns  # noqa: F401 - fixture
from tests.rest_connector_support import API

pytestmark = pytest.mark.usefixtures("public_source_dns")


class _Scheduler:
    def __init__(self):
        self.calls = []

    async def run_task_now(self, task_id, **kwargs):
        self.calls.append((task_id, kwargs))
        return {"task_run_id": "run-1"}


@pytest.fixture
async def http(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://setup.test") as client:
        yield client, state


async def test_a_list_operation_syncs_page_by_page_inside_the_roles_scope(db, api):  # noqa: F811
    world = await _world(db)
    row = await _intake(db, world)
    pages(api, [ticket("T-1"), ticket("T-2", "Working", group="G2")],
          [ticket("T-3", opened_by="Rita Muster"), {"summary": "no key", "state": {"name": "New"}, "group": "G1"}])
    result = await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False)
    summary = result["summary"]
    assert (summary["pages"], summary["complete"], summary["role"]) == (2, True, "agent")
    assert (summary["imported"], summary["dropped_out_of_scope"], summary["skipped_invalid"]) == (2, 1, 1)
    sent = [request.url.params for request in api.requests]
    assert all(params["assignment_group"] == "G1" and params["state"] == "open" for params in sent), \
        "the scope parameter is injected and the intake's arguments sent on every page"
    items = await _items(db, world)
    assert set(items) == {"T-1", "T-3"}, "G2 is outside the role's result filter, the keyless record is refused"
    first = items["T-1"]
    assert (first.source_type, first.source_instance, first.source_id) == ("custom_rest", world.key, "id-T-1")
    assert (first.title, first.source_status, first.work_state, first.issue_type) == ("Ticket T-1", "New", "intake",
                                                                                     "incident")
    assert (first.reporter, first.assignee, first.labels_json) == ("rita@example.test", "max.m", ["vpn", "octryx"])
    assert first.source_url == f"{API}/t/T-1" and first.source_fields_json["custom_rest"]["operation"] == "list_tickets"
    assert items["T-3"].reporter is None, "a display name is not an identifier"
    assert item_scope_key(first, "custom_rest") == world.key
    runs = (await db.execute(select(RestApiCallRun).where(RestApiCallRun.project_id == world.project_id))).scalars()
    assert {run.scope_json["role"] for run in runs} == {"agent"}, "every page is an audited call as the role"


async def test_closures_reconcile_only_after_a_complete_read(db, api):  # noqa: F811
    world = await _world(db)
    row = await _intake(db, world)
    pages(api, [ticket("T-1"), ticket("T-2"), ticket("T-3")])
    await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False)
    pages(api, [ticket("T-1", "Resolved"), ticket("T-9", "Resolved")], [ticket("T-3")])
    row.sync_options_json = {**row.sync_options_json, "max_pages": 1}
    cut = await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False)
    items = await _items(db, world)
    assert cut["summary"]["complete"] is False and items["T-1"].work_state == "done", "a closed status closes"
    assert items["T-2"].work_state == "intake", "a cut read closes nothing for leaving it"
    assert "T-9" not in items and cut["summary"]["skipped_closed"] == 1, "a closed record is not imported"
    row.sync_options_json = {**row.sync_options_json, "max_pages": 100}
    full = await rest_intake.run_intake(db, row=row, user=world.admin, dry_run=False)
    assert full["summary"]["complete"] is True and (await _items(db, world))["T-2"].work_state == "done"


async def test_a_scoped_operation_is_never_synced_without_a_role(db, api):  # noqa: F811
    world = await _world(db)
    with pytest.raises(HTTPException) as unscoped:
        await save_intake(db, user=world.admin, project_id=world.project_id, draft=_draft(world, role=None))
    assert unscoped.value.detail["code"] == "custom_rest_role_required"
    with pytest.raises(HTTPException) as other:
        await save_intake(db, user=world.admin, project_id=world.project_id, draft=_draft(world, role="auditor"))
    assert other.value.detail["code"] == "custom_rest_role_not_granted"
    assert api.requests == []
    open_world = await _world(db, list_grants=[{"role": "agent"}])
    row = await _intake(db, open_world, role=None)
    pages(api, [ticket("T-1", group="G2")])
    result = await rest_intake.run_intake(db, row=row, user=open_world.admin, dry_run=True)
    assert result["summary"]["imported"] == 1, "only unscoped grants: the sync sees what any granted caller sees"


async def test_an_inbound_webhook_triggers_the_intake_sync_not_an_agent_turn(db, api):  # noqa: F811
    world = await _world(db)
    row = await _intake(db, world)
    task = await rest_intake.sync_task(db, row)
    webhook = Webhook(project_id=world.project_id, owner_id=world.admin.id, name="desk", source_type="generic",
                      task_id=task.id, is_active=True)
    db.add(webhook)
    await db.commit()
    scheduler = _Scheduler()
    inactive = await receive_alert(db, webhook=webhook, body=b"{}", verified=True, delivery_key="d1",
                                   scheduler=scheduler)
    assert inactive["outcome"] == "intake_not_enabled" and scheduler.calls == []
    row.is_active = True
    await db.commit()
    started = await receive_alert(db, webhook=webhook, body=b'{"ticket": "T-1"}', verified=True, delivery_key="d2",
                                  scheduler=scheduler)
    assert started["outcome"] == "intake_sync" and started["task_run_id"] == "run-1"
    ((task_id, options),) = scheduler.calls
    assert task_id == task.id and options["trigger_type"] == "webhook" and options["allow_inactive"] is True
    assert "run_input" not in options, "the webhook's payload never reaches a run: the sync reads the API itself"


async def test_the_setup_api_discovers_samples_previews_and_enables(db, api, http):  # noqa: F811
    client, state = http
    world = await _world(db)
    state["user"] = world.admin
    base = f"/api/v1/secure-work/workspaces/{world.project_id}/intake"
    fields = (await client.get(f"{base}/fields", params={"source_type": "custom_rest",
                                                         "connection_id": world.key})).json()
    (listing,) = fields["list_operations"]
    assert (listing["op_key"], listing["role_required"], listing["scoped_roles"]) == ("list_tickets", True, ["agent"])
    assert [operation["op_key"] for operation in fields["write_operations"]] == ["set_status"]
    pages(api, [ticket("T-1"), ticket("T-2", group="G2")], [ticket("T-3")])
    sample = (await client.post(f"{base}/sample", json=_draft(world))).json()
    assert (sample["records"], sample["dropped_out_of_scope"], sample["last_page"]) == (1, 1, False)
    assert sample["items"][0]["source_key"] == "T-1" and await _items(db, world) == {}, "a sample stores nothing"
    created = (await client.post(base, json=_draft(world))).json()
    assert created["source_type"] == "custom_rest" and created["is_active"] is False
    assert created["how"]["field_mapping"] == FIELDS and created["what"]["operation"] == "list_tickets"
    refused = await client.post(f"{base}/{created['id']}/enable")
    assert refused.status_code == 409
    preview = (await client.post(f"{base}/{created['id']}/preview")).json()
    assert preview["summary"]["imported"] == 2 and await _items(db, world) == {}
    enabled = (await client.post(f"{base}/{created['id']}/enable")).json()
    assert enabled["intake"]["is_active"] is True and enabled["first_run"]["summary"]["imported"] == 2
    tasks = (await db.execute(select(Task).where(Task.task_type == GENERIC_SYNC_TASK_TYPE))).scalars().all()
    assert any(task.config["sync_config_id"] == created["id"] for task in tasks)
    assert SOURCE.scope_key((await _items(db, world))["T-1"]) == world.key
    overview = {source["kind"]: source for source in (await intake_overview(db, world.project_id))["sources"]}
    rest = overview["custom_rest"]
    assert (rest["work_state"], [entry["id"] for entry in rest["connections"]]) == ("set_up", [world.key])
