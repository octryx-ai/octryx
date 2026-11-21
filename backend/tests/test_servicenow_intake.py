"""Contract: ServiceNow incidents and changes become the Workspace's work items.

Against the ``servicenow.test`` stub (password grant, Scripted REST or Table API): preview counts without
writing, sync deduplicated by ``sys_id`` with every mapped field and the ``nav_to`` link, the configurable state
mapping, closing (a closed state, or leaving a complete open set) with a state event, no regression of a local
transition, the item's own notes kept, the configured endpoint style, validation, and the schedule.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Scheduler, Task, WorkItem, WorkItemStateEvent, WorkItemSyncRun
from app.services.secure_work.intake.scheduled import run_scheduled_intake
from app.services.secure_work.servicenow.config import normalize_intake
from app.services.secure_work.servicenow.intake import (
    SERVICENOW_SYNC_TASK_TYPE,
    put_intake,
    run_intake,
)
from tests.servicenow_intake_support import (
    CHANGES_PATH,
    INCIDENTS_PATH,
    TABLE_PATH,
    WritingStub,
    incident,
    stub,
    workspace,
)
from tests.servicenow_stub_support import SN_URL, record, sys_id

OPEN = [incident(1, "New"), incident(2, "In Progress"), incident(3, "On Hold"), incident(4, "Resolved")]


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    instance.data[INCIDENTS_PATH] = list(OPEN)
    yield from stub(monkeypatch, instance)


async def _intake(db, payload=None, **connection):
    project_id, admin = await workspace(db, **connection)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", **(payload or {})}, user=admin)
    await db.commit()
    return project_id, admin, row


async def _items(db, project_id) -> dict[str, WorkItem]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return {row.source_key: row for row in rows}


async def test_the_preview_counts_without_writing(db, sn):
    project_id, admin, row = await _intake(db)
    result = await run_intake(db, row=row, user=admin, dry_run=True)
    summary = result["summary"]
    assert (summary["open"], summary["imported"], summary["skipped_closed"], summary["complete"]) == (3, 3, 1, True)
    # Newest first (follow-ups 2): the open records by number, descending.
    assert [item["source_key"] for item in result["items"]] == ["INC0000003", "INC0000002", "INC0000001"]
    assert result["items"][-1]["source_url"] == f"{SN_URL}/nav_to.do?uri=incident.do%3Fsys_id%3D{sys_id(1)}"
    assert await _items(db, project_id) == {}
    assert result["sync_run"]["mode"] == "dry_run"


async def test_the_sync_creates_items_with_every_mapped_field(db, sn):
    project_id, admin, row = await _intake(db)
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert (summary["imported"], summary["skipped_closed"]) == (3, 1)
    items = await _items(db, project_id)
    assert set(items) == {"INC0000001", "INC0000002", "INC0000003"}, "a closed record is never imported"
    first = items["INC0000001"]
    assert (first.source_type, first.source_id, first.issue_type, first.title) == (
        "servicenow", sys_id(1), "incident", "Record 1")
    assert (first.description, first.priority, first.assignee) == ("Details", "3 - Moderate", "Test User")
    assert first.source_url.endswith(f"nav_to.do?uri=incident.do%3Fsys_id%3D{sys_id(1)}")
    assert first.source_instance == "servicenow.test" and first.source_created_at is not None
    assert first.source_fields_json["servicenow"]["assignment_group"] == "Test Group"
    assert {key: item.work_state for key, item in items.items()} == {
        "INC0000001": "intake", "INC0000002": "development", "INC0000003": "blocked"}
    assert row.last_sync_status == "completed"


async def test_a_rerun_deduplicates_by_sys_id_and_keeps_the_items_own_notes(db, sn):
    project_id, admin, row = await _intake(db)
    await run_intake(db, row=row, user=admin, dry_run=False)
    items = await _items(db, project_id)
    items["INC0000001"].source_fields_json = {**items["INC0000001"].source_fields_json,
                                              "platform_notes": [{"note": "keep me"}]}
    await db.flush()
    sn.data[INCIDENTS_PATH][0] = {**OPEN[0], "number": "INC9999999", "short_description": "Renamed"}
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert (summary["imported"], summary["updated"], summary["unchanged"]) == (0, 1, 2)
    items = await _items(db, project_id)
    renamed = items["INC9999999"]
    assert renamed.title == "Renamed" and "INC0000001" not in items, "the same sys_id, one item"
    assert renamed.source_fields_json["platform_notes"] == [{"note": "keep me"}]


async def test_closing_in_servicenow_moves_the_item_to_done_with_a_state_event(db, sn):
    project_id, admin, row = await _intake(db)
    await run_intake(db, row=row, user=admin, dry_run=False)
    sn.data[INCIDENTS_PATH][1] = incident(2, "Closed")
    preview = (await run_intake(db, row=row, user=admin, dry_run=True))["summary"]
    assert preview["closed"] == 1 and (await _items(db, project_id))["INC0000002"].work_state == "development"
    assert (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]["closed"] == 1
    item = (await _items(db, project_id))["INC0000002"]
    assert (item.work_state, item.sync_state) == ("done", "closed_at_source")
    event = (await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item.id))).scalar_one()
    assert (event.from_state, event.to_state, event.source) == ("development", "done", "servicenow")
    sn.data[INCIDENTS_PATH][1] = incident(2, "New")  # reopened: the sync's own closure is no local transition
    await run_intake(db, row=row, user=admin, dry_run=False)
    assert (await _items(db, project_id))["INC0000002"].work_state == "intake"


async def test_a_record_that_leaves_a_complete_open_set_is_closed_and_a_truncated_one_is_not(db, sn):
    project_id, admin, row = await _intake(db, {"max_items": 3})
    await run_intake(db, row=row, user=admin, dry_run=False)
    sn.data[INCIDENTS_PATH] = [OPEN[0], OPEN[1]]
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert summary["complete"] is True and summary["closed"] == 1
    assert (await _items(db, project_id))["INC0000003"].work_state == "done"
    sn.data[INCIDENTS_PATH] = [incident(i, "New") for i in range(10, 15)]  # more than max_items: incomplete
    truncated = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert truncated["complete"] is False and truncated["closed"] == 0
    assert (await _items(db, project_id))["INC0000001"].work_state != "done"


async def test_a_local_transition_is_never_regressed_but_a_closure_still_applies(db, sn):
    project_id, admin, row = await _intake(db)
    await run_intake(db, row=row, user=admin, dry_run=False)
    item = (await _items(db, project_id))["INC0000001"]
    db.add(WorkItemStateEvent(work_item_id=item.id, from_state="intake", to_state="review", actor_id=admin.id,
                              source="manual"))
    item.work_state = "review"
    await db.flush()
    await run_intake(db, row=row, user=admin, dry_run=False)
    assert (await _items(db, project_id))["INC0000001"].work_state == "review"
    sn.data[INCIDENTS_PATH][0] = incident(1, "Resolved")
    await run_intake(db, row=row, user=admin, dry_run=False)
    assert (await _items(db, project_id))["INC0000001"].work_state == "done"


async def test_the_state_mapping_is_configurable_and_an_unmapped_state_is_reported(db, sn):
    sn.data[INCIDENTS_PATH] = [incident(1, "Awaiting Vendor"), incident(2, "In Progress")]
    project_id, admin, row = await _intake(db, {"state_mapping": {"In Progress": "validation"}})
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    items = await _items(db, project_id)
    assert items["INC0000002"].work_state == "validation" and items["INC0000001"].work_state == "intake"
    assert summary["unmapped_states"] == 1
    assert items["INC0000001"].source_fields_json["servicenow"]["state_mapping"] == "unmapped"


async def test_changes_are_listed_when_configured(db, sn):
    sn.data[CHANGES_PATH] = [{**record(500, "CHG"), "state": "New"}]
    project_id, admin, row = await _intake(db, {"tables": ["incident", "change_request"]})
    await run_intake(db, row=row, user=admin, dry_run=False)
    change = (await _items(db, project_id))["CHG0000500"]
    assert change.issue_type == "change_request" and "uri=change_request.do" in change.source_url


async def test_the_table_api_style_lists_active_records_with_display_values(db, sn):
    sn.data[TABLE_PATH] = [incident(1, "New")]
    sn.list_keys[TABLE_PATH] = "result"
    project_id, admin, row = await _intake(db, {"sysparm_query": "priority=1"}, servicenow_api_style="table")
    await run_intake(db, row=row, user=admin, dry_run=False)
    path, params, _auth = sn.api_requests[-1]
    assert path == TABLE_PATH and params["sysparm_query"] == "priority=1^ORDERBYDESCnumber"
    assert params["sysparm_display_value"] == "true"
    assert set(await _items(db, project_id)) == {"INC0000001"}


async def test_without_a_connection_the_intake_answers_its_code(db, sn):
    from app.services.secure_work.servicenow.source import IntakeSourceError

    project_id, admin, row = await _intake(db, servicenow_url="")
    with pytest.raises(IntakeSourceError) as refused:
        await run_intake(db, row=row, user=admin, dry_run=True)
    assert refused.value.code == "servicenow_connection_not_configured"


@pytest.mark.parametrize("payload", [
    {"tables": []}, {"tables": ["problem"]}, {"state_mapping": {"New": "nowhere"}},
    {"sysparm_query": "active=true^NQactive=false"}, {"schedule": {"preset": "weekly"}},
    {"schedule": {"preset": "custom", "cron": "nope"}}, {"max_items": 0}, {"max_items": 1001}, {"excluded_states": "Closed"},
])
def test_the_configuration_is_validated(payload):
    with pytest.raises(HTTPException) as refused:
        normalize_intake(payload)
    assert refused.value.status_code == 422


def test_the_defaults():
    defaults = normalize_intake({})
    assert defaults["tables"] == ["incident"] and defaults["schedule"] == {"preset": "every_15_min", "cron": None}
    assert defaults["max_items"] == 200
    assert {"Closed", "Resolved", "Cancelled"} <= set(defaults["excluded_states"])
    assert defaults["state_mapping"]["on hold"] == "blocked"


async def test_the_schedule_is_a_deterministic_task_and_runs_the_sync(db, sn):
    project_id, admin, row = await _intake(db, {"schedule": {"preset": "custom", "cron": "*/30 * * * *"}})
    task = (await db.execute(select(Task).where(Task.task_type == SERVICENOW_SYNC_TASK_TYPE))).scalars().all()
    task = next(entry for entry in task if entry.config["sync_config_id"] == row.id)
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalar_one()
    assert (scheduler.cron_expression, scheduler.is_active, task.is_active) == ("*/30 * * * *", True, True)

    class Run:
        output = None

    output = await run_scheduled_intake(db, task=task, task_run=Run())
    assert output["summary"]["imported"] == 3 and output["mode"] == SERVICENOW_SYNC_TASK_TYPE
    await put_intake(db, project_id=project_id, payload={"connection_id": "default", "schedule": {"preset": "manual"}},
                     user=admin)
    assert scheduler.is_active is False, "manual turns the schedule off"
    runs = (await db.execute(select(WorkItemSyncRun).where(WorkItemSyncRun.sync_config_id == row.id))).scalars()
    assert [run.mode for run in runs] == ["sync"]


async def test_the_scheduler_entry_still_runs_jira_tasks(db, monkeypatch):
    import app.services.secure_work.jira.jira_sync_task as jira_sync_task

    calls = []

    async def jira(db, *, task, task_run):
        calls.append(task.task_type)
        return {"mode": "jira"}

    monkeypatch.setattr(jira_sync_task, "run_scheduled_jira_work_item_sync", jira)
    task = Task(dispatch_binding="task_definition", name="j", task_type="secure_work_jira_sync", config={}, owner_id="x")
    assert await run_scheduled_intake(db, task=task, task_run=None) == {"mode": "jira"}
    assert calls == ["secure_work_jira_sync"]
