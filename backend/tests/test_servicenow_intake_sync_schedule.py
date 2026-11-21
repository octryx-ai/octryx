"""Contract: the ServiceNow intake syncs regularly, closures at the source propagate, and it can be synced now.

- a new intake is scheduled every 15 minutes (the Jira intake's scheduler pattern), ``manual`` turns it off;
- a Table API run also reads the records changed since the last successful sync (with an overlap, server-side
  relative condition) in any state, so a record closed at the source closes this intake's item even when the
  open listing is truncated, with the record's state as ``source_status``; never an import, never another
  intake's item; a dry run only counts;
- ``POST /workspaces/{id}/intake/{intake_id}/sync``: Workspace admins or owners, enabled intakes only, audited,
  with an explicit result. Stub only, no network.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.secure_work_intake_setup import router
from app.db import get_db
from app.models import AuditLog, Scheduler, Task, UserProject, WorkItem, WorkItemSyncConfig
from app.services.auth import get_current_user
from app.services.secure_work.intake.sync_now import CODE_NOT_ENABLED, SYNC_NOW_AUDIT_ACTION
from app.services.secure_work.servicenow.changed_since import OVERLAP_MINUTES, window_minutes
from app.services.secure_work.servicenow.config import normalize_intake
from app.services.secure_work.servicenow.intake import SERVICENOW_SYNC_TASK_TYPE, put_intake, run_intake
from app.time_utils import utc_now
from tests.servicenow_intake_support import TABLE_PATH, WritingStub, incident, stub, workspace
from tests.test_jira_task_list_governance import _operator

FIELD_CASE = 104  # INC0000104: closed at the source, must close locally


class ChangedStub(WritingStub):
    """The Table API answers the open listing, or ``changed`` for the changed-since query."""

    def __init__(self):
        super().__init__(incidents=0, changes=0)
        self.list_keys[TABLE_PATH] = "result"
        self.data[TABLE_PATH] = []
        self.changed: list[dict] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("sysparm_query", "")
        if request.url.path == TABLE_PATH and "sys_updated_onRELATIVEGT@minute@ago@" in query:
            open_listing, self.data[TABLE_PATH] = self.data[TABLE_PATH], self.changed
            try:
                return await super().handle(request)
            finally:
                self.data[TABLE_PATH] = open_listing
        return await super().handle(request)


@pytest.fixture
def sn(monkeypatch):
    yield from stub(monkeypatch, ChangedStub())


async def _table_intake(db, payload=None):
    project_id, admin = await workspace(db, servicenow_api_style="table")
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", **(payload or {})}, user=admin)
    await db.commit()
    return project_id, admin, row


async def _items(db, project_id) -> dict[str, WorkItem]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return {row.source_key: row for row in rows}


def _changed_queries(sn) -> list[str]:
    return [params["sysparm_query"] for path, params, _ in sn.api_requests
            if path == TABLE_PATH and "RELATIVEGT" in params.get("sysparm_query", "")]


async def _scheduler(db, row) -> tuple[Task, Scheduler]:
    tasks = (await db.execute(select(Task).where(Task.task_type == SERVICENOW_SYNC_TASK_TYPE))).scalars().all()
    task = next(entry for entry in tasks if entry.config["sync_config_id"] == row.id)
    return task, (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalar_one()


async def test_a_new_intake_is_scheduled_every_15_minutes_and_manual_turns_it_off(db, sn):
    assert normalize_intake({})["schedule"] == {"preset": "every_15_min", "cron": None}
    project_id, admin, row = await _table_intake(db)
    task, scheduler = await _scheduler(db, row)
    assert (scheduler.cron_expression, scheduler.is_active, task.is_active) == ("*/15 * * * *", True, True)
    assert task.config["local_execution"] == "deterministic"
    await put_intake(db, project_id=project_id, payload={"connection_id": "default", "schedule": {"preset": "hourly"}},
                     user=admin)
    assert (scheduler.cron_expression, scheduler.is_active) == ("0 * * * *", True)
    await put_intake(db, project_id=project_id, payload={"connection_id": "default", "schedule": {"preset": "manual"}},
                     user=admin)
    assert scheduler.is_active is False and task.is_active is False


def test_the_window_runs_from_the_last_successful_sync_with_an_overlap():
    now = utc_now()
    row = WorkItemSyncConfig(name="x", source_type="servicenow")
    assert window_minutes(row, now) is None, "no successful sync yet: nothing is read"
    row.last_sync_at, row.last_sync_status = now - timedelta(minutes=10, seconds=20), "completed"
    assert window_minutes(row, now) == 11 + OVERLAP_MINUTES
    row.last_sync_status = "failed"
    assert window_minutes(row, now) is None


async def test_a_record_closed_at_the_source_closes_its_item_although_the_open_listing_is_truncated(db, sn):
    sn.data[TABLE_PATH] = [incident(FIELD_CASE, "In Progress"), incident(2, "New")]
    project_id, admin, row = await _table_intake(db, {"max_items": 2})
    first = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert first["imported"] == 2 and first["changed_window_minutes"] is None and _changed_queries(sn) == []

    # Closed at the source: it left ``active=true``, and the open listing is cut (more open records than max_items).
    sn.data[TABLE_PATH] = [incident(i, "New") for i in (2, 10, 11)]
    sn.changed = [incident(FIELD_CASE, "Closed"), incident(999, "Closed"), incident(2, "New")]
    preview = (await run_intake(db, row=row, user=admin, dry_run=True))["summary"]
    assert preview["closed_since_last_sync"] == 1 and preview["complete"] is False
    assert (await _items(db, project_id))["INC0000104"].work_state != "done", "a dry run only counts"

    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert (summary["closed_since_last_sync"], summary["closed"], summary["changed_complete"]) == (1, 1, True)
    assert summary["changed_window_minutes"] >= OVERLAP_MINUTES
    items = await _items(db, project_id)
    closed = items["INC0000104"]
    assert (closed.work_state, closed.sync_state, closed.source_status) == ("done", "closed_at_source", "Closed")
    assert "INC0000999" not in items, "a closed record without an item is never imported"
    assert items["INC0000002"].work_state != "done"
    query = _changed_queries(sn)[-1]
    assert query.startswith("sys_updated_onRELATIVEGT@minute@ago@") and query.endswith("^ORDERBYDESCnumber")
    assert "active=true" not in query, "closed records are read too"


async def test_a_closure_since_the_last_sync_never_touches_another_intakes_item(db, sn):
    sn.data[TABLE_PATH] = [incident(FIELD_CASE, "In Progress")]
    project_id, admin, row = await _table_intake(db)
    await run_intake(db, row=row, user=admin, dry_run=False)
    item = (await _items(db, project_id))["INC0000104"]
    other = WorkItemSyncConfig(name="other", project_id=project_id, source_type="servicenow", created_by=admin.id)
    db.add(other)
    await db.flush()
    item.sync_config_id = other.id
    await db.flush()
    sn.data[TABLE_PATH] = [incident(i, "New") for i in range(10, 300)]  # truncated at max_items 200
    sn.changed = [incident(FIELD_CASE, "Resolved")]
    assert (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]["closed_since_last_sync"] == 0
    assert (await _items(db, project_id))["INC0000104"].work_state != "done"


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://setup.test") as client:
        yield client, state


async def test_sync_now_is_for_admins_of_an_enabled_intake_audited_with_an_explicit_result(db, sn, api):
    client, state = api
    sn.data[TABLE_PATH] = [incident(1, "New"), incident(2, "In Progress")]
    project_id, admin, row = await _table_intake(db)
    route = f"/api/v1/secure-work/workspaces/{project_id}/intake/{row.id}/sync"
    member = await _operator(db)
    db.add(UserProject(user_id=member.id, project_id=project_id, role="member"))
    await db.commit()

    state["user"] = member
    assert (await client.post(route)).status_code == 403
    state["user"] = admin
    assert (await client.post(f"/api/v1/secure-work/workspaces/{project_id}/intake/missing/sync")).status_code == 404
    row.is_active = False
    await db.commit()
    refused = await client.post(route)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == CODE_NOT_ENABLED
    row.is_active = True
    await db.commit()

    synced = await client.post(route)
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert (body["state"], body["intake_id"], body["source_type"], body["trigger"]) == (
        "ran", row.id, "servicenow", "manual")
    assert body["summary"]["imported"] == 2 and body["sync_run"]["mode"] == "sync"
    assert set(await _items(db, project_id)) == {"INC0000001", "INC0000002"}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == SYNC_NOW_AUDIT_ACTION,
                                                     AuditLog.resource_id == row.id))).scalar_one()
    assert audit.user_id == admin.id and audit.details["sync_run_id"] == body["sync_run"]["id"]


async def test_sync_now_answers_a_source_failure_with_its_code(db, sn, api):
    client, state = api
    project_id, admin, row = await _table_intake(db)
    state["user"] = admin
    sn.api_answer[TABLE_PATH] = (500, None)
    failed = await client.post(f"/api/v1/secure-work/workspaces/{project_id}/intake/{row.id}/sync")
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "servicenow_endpoint_http_status"
