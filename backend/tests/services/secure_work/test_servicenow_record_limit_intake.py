"""The ServiceNow intake imports only the connector's groups and rechecks each Table API record, an override can only narrow, a connector narrowed after saving refuses the run, and out-of-scope or bound-cut listings close nothing."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import WorkItem
from app.services.secure_work.servicenow.intake import limit_scope, put_intake, run_intake
from app.services.secure_work.servicenow.source import IntakeSourceError
from tests.servicenow_intake_support import INCIDENTS_PATH, TABLE_PATH, incident, workspace
from tests.support.servicenow_record_limit_support import DESK, NET, NET_ID, as_all, sn  # noqa: F401

# --- the intake --------------------------------------------------------------------------------------------------


async def _items(db, project_id) -> dict[str, WorkItem]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return {row.source_key: row for row in rows}


async def test_the_scripted_intake_imports_only_the_connectors_groups(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [incident(1, "New", assignment_group="Network Ops"),
                               incident(2, "New", assignment_group="Service Desk"),
                               incident(3, "New", assignment_group="Database")]
    project_id, admin = await workspace(db, servicenow_assignment_groups=["Network Ops", "Service Desk"])
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert set(await _items(db, project_id)) == {"INC0000001", "INC0000002"}
    assert summary["assignment_groups"] == ["Network Ops", "Service Desk"]


async def test_the_table_api_intake_adds_the_condition_and_rechecks_each_record(db, sn):  # noqa: F811
    sn.data[TABLE_PATH] = [as_all(incident(1, "New", assignment_group=NET)),
                           as_all(incident(2, "New", assignment_group=DESK))]
    sn.list_keys[TABLE_PATH] = "result"
    project_id, admin = await workspace(db, servicenow_api_style="table", servicenow_assignment_groups=[NET_ID])
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "sysparm_query": "priority=1"}, user=admin)
    await run_intake(db, row=row, user=admin, dry_run=False)
    _path, params, _auth = sn.api_requests[-1]
    assert params["sysparm_query"] == f"assignment_groupIN{NET_ID}^priority=1^ORDERBYDESCnumber"
    assert params["sysparm_display_value"] == "all"
    items = await _items(db, project_id)
    assert set(items) == {"INC0000001"}
    stored = items["INC0000001"].source_fields_json["servicenow"]
    assert (stored["assignment_group"], stored["assignment_group_sys_id"]) == ("Network Ops", NET_ID)
    assert items["INC0000001"].title == "Record 1"  # display values, as without a limit


async def test_the_intake_override_narrows_and_can_never_widen(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [incident(1, "New", assignment_group="Network Ops"),
                               incident(2, "New", assignment_group="Service Desk")]
    project_id, admin = await workspace(db, servicenow_assignment_groups=["Network Ops", "Service Desk"])
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "assignment_groups": ["service desk"]}, user=admin)
    await run_intake(db, row=row, user=admin, dry_run=False)
    assert set(await _items(db, project_id)) == {"INC0000002"}
    scope = await limit_scope(db, project_id, {"assignment_groups": ["service desk"]})
    assert scope["assignment_group_scope"] == {"connector": ["Network Ops", "Service Desk"],
                                               "intake": ["service desk"], "effective": ["service desk"]}
    assert scope["service_scope"] == {"connector": [], "intake": [], "effective": []}
    with pytest.raises(HTTPException) as refused:
        await put_intake(db, project_id=project_id, payload={"connection_id": "default", "assignment_groups": ["Database"]}, user=admin)
    assert refused.value.status_code == 422 and refused.value.detail["field"] == "assignment_groups"


async def test_a_connector_narrowed_after_saving_refuses_the_run_instead_of_widening(db, sn):  # noqa: F811
    from app.models import BuiltInToolConfig

    project_id, admin = await workspace(db, servicenow_assignment_groups=["Network Ops", "Service Desk"])
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "assignment_groups": ["Service Desk"]}, user=admin)
    entry = (await db.execute(select(BuiltInToolConfig).where(BuiltInToolConfig.project_id == project_id))
             ).scalar_one()
    entry.config = {**entry.config, "servicenow_assignment_groups": ["Network Ops"]}
    await db.commit()
    with pytest.raises(IntakeSourceError) as refused:
        await run_intake(db, row=row, user=admin, dry_run=True)
    assert refused.value.code == "servicenow_assignment_groups_not_allowed"
    scope = await limit_scope(db, project_id, {"assignment_groups": ["Service Desk"]})
    assert scope["assignment_group_scope"]["effective"] is None


async def test_items_of_other_groups_are_out_of_scope_and_never_closed_as_left(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [incident(1, "New", assignment_group="Network Ops"),
                               incident(2, "New", assignment_group="Service Desk")]
    project_id, admin = await workspace(db)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await run_intake(db, row=row, user=admin, dry_run=False)  # before the limit: both imported
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "assignment_groups": ["Network Ops"]}, user=admin)
    sn.data[INCIDENTS_PATH] = [incident(2, "New", assignment_group="Service Desk")]  # INC1 left the open set
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    items = await _items(db, project_id)
    assert items["INC0000001"].work_state == "done" and summary["closed"] == 1
    assert items["INC0000002"].work_state != "done", "another group's item is out of scope, not closed"


async def test_a_listing_cut_by_the_scan_bound_is_incomplete_and_closes_nothing(db, sn, monkeypatch):  # noqa: F811
    import app.services.secure_work.servicenow.source as source

    sn.data[INCIDENTS_PATH] = [incident(1, "New", assignment_group="Network Ops")]
    project_id, admin = await workspace(db, servicenow_assignment_groups=["Network Ops"],
                                        servicenow_page_size=1)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await run_intake(db, row=row, user=admin, dry_run=False)
    # INC1 is now behind three records of another group; the scan stops before it is seen again.
    sn.data[INCIDENTS_PATH] = [incident(i, "New", assignment_group="Service Desk") for i in (5, 6, 7)] + [
        incident(1, "New", assignment_group="Network Ops")]
    monkeypatch.setattr(source, "MAX_SCANNED", 2)
    summary = (await run_intake(db, row=row, user=admin, dry_run=False))["summary"]
    assert summary["complete"] is False and summary["closed"] == 0
    assert (await _items(db, project_id))["INC0000001"].work_state != "done"
