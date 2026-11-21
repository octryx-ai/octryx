"""The ServiceNow intake imports group and service, keeps open records newest first under the limit, never closes records outside it, and the known-values suggestions stay inside the limit for workspace admins only."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models import UserProject, WorkItem
from app.services.secure_work.servicenow.intake import limit_scope, put_intake, run_intake
from app.services.secure_work.servicenow.known_values import known_values
from tests.servicenow_intake_support import INCIDENTS_PATH, TABLE_PATH, workspace
from tests.servicenow_services_limit_support import CLOUD, DESK, row, sn  # noqa: F401
from tests.servicenow_stub_support import config

# --- the intake --------------------------------------------------------------------------------------------------


async def _items(db, project_id) -> dict[str, WorkItem]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return {item.source_key: item for item in rows}


async def test_the_intake_imports_group_and_service_and_keeps_the_service(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [row(1, DESK, "Checkout"), row(2, DESK, "Parcel Tracking"), row(3, CLOUD, "Checkout")]
    project_id, admin = await workspace(db, servicenow_assignment_groups=["Shop Support Desk", CLOUD],
                                        servicenow_services=["Checkout"])
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "assignment_groups": [CLOUD]}, user=admin)
    summary = (await run_intake(db, row=intake, user=admin, dry_run=False))["summary"]
    items = await _items(db, project_id)
    assert set(items) == {"INC0000003"}
    assert items["INC0000003"].source_fields_json["servicenow"]["service"] == "Checkout"
    assert (summary["assignment_groups"], summary["services"], summary["filter_mode"]) == ([CLOUD], ["Checkout"], "all")
    scope = await limit_scope(db, project_id, {"assignment_groups": [CLOUD], "services": []})
    assert scope["service_scope"] == {"connector": ["Checkout"], "intake": [], "effective": ["Checkout"]}
    assert scope["assignment_group_scope"]["effective"] == [CLOUD] and scope["filter_mode"] == "all"
    with pytest.raises(HTTPException) as refused:
        await put_intake(db, project_id=project_id, payload={"connection_id": "default", "services": ["Parcel Tracking"]}, user=admin)
    assert refused.value.status_code == 422 and refused.value.detail["field"] == "services"


async def test_items_outside_the_service_limit_are_never_closed_as_left(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [row(1, DESK, "Checkout"), row(2, DESK, "Parcel Tracking")]
    project_id, admin = await workspace(db)
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await run_intake(db, row=intake, user=admin, dry_run=False)  # before the limit: both imported
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "services": ["Checkout"]}, user=admin)
    sn.data[INCIDENTS_PATH] = [row(2, DESK, "Parcel Tracking")]  # INC1 left the open set
    summary = (await run_intake(db, row=intake, user=admin, dry_run=False))["summary"]
    items = await _items(db, project_id)
    assert items["INC0000001"].work_state == "done" and summary["closed"] == 1
    assert items["INC0000002"].work_state != "done", "another service's item is out of scope, not closed"


async def test_open_records_are_never_lost_to_closed_ones_on_scripted_rest(db, sn):  # noqa: F811
    # The endpoint lists oldest first: 6 closed records before the open ones, max_items 3.
    sn.data[INCIDENTS_PATH] = [row(i, DESK, "Checkout", "Closed") for i in range(1, 7)] + [
        row(i, DESK, "Checkout", "New") for i in (7, 8)]
    project_id, admin = await workspace(db, servicenow_page_size=2)
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "max_items": 3}, user=admin)
    summary = (await run_intake(db, row=intake, user=admin, dry_run=False))["summary"]
    assert set(await _items(db, project_id)) == {"INC0000007", "INC0000008"}
    assert (summary["open"], summary["skipped_closed"], summary["complete"]) == (2, 6, True)
    # One of the open ones closes later: closed by its own record, behind three more closed ones.
    sn.data[INCIDENTS_PATH] = [row(i, DESK, "Checkout", "Closed") for i in range(1, 8)] + [
        row(i, DESK, "Checkout", "Closed") for i in (9, 10, 11)] + [row(8, DESK, "Checkout", "New")]
    summary = (await run_intake(db, row=intake, user=admin, dry_run=False))["summary"]
    items = await _items(db, project_id)
    assert items["INC0000007"].work_state == "done" and items["INC0000008"].work_state != "done"
    assert summary["closed"] == 1 and summary["open"] == 1


async def test_more_open_records_than_max_items_keep_the_newest_and_close_nothing(db, sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [row(i, DESK, "Checkout") for i in range(1, 6)]
    project_id, admin = await workspace(db)
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default", "max_items": 2}, user=admin)
    result = await run_intake(db, row=intake, user=admin, dry_run=True)
    assert [item["source_key"] for item in result["items"]] == ["INC0000005", "INC0000004"]
    assert result["summary"]["complete"] is False and result["summary"]["closed"] == 0


async def test_the_table_api_intake_reads_newest_first(db, sn):  # noqa: F811
    sn.data[TABLE_PATH] = [row(2, DESK, "Checkout"), row(1, DESK, "Checkout")]
    sn.list_keys[TABLE_PATH] = "result"
    project_id, admin = await workspace(db, servicenow_api_style="table")
    intake = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await run_intake(db, row=intake, user=admin, dry_run=True)
    _path, params, _auth = sn.api_requests[-1]
    assert params["sysparm_query"] == "active=true^ORDERBYDESCnumber"


# --- known values ------------------------------------------------------------------------------------------------


async def test_known_values_count_names_inside_the_limit_or_everything(sn):  # noqa: F811
    sn.data[INCIDENTS_PATH] = [row(1, DESK, "Checkout"), row(2, "Shop Support Desk", "Checkout"),
                               row(3, DESK, "Parcel Tracking"), row(4, CLOUD, "Checkout")]
    everything = await known_values(config(), limited=False)
    assert everything["scanned"] == 4
    assert everything["assignment_groups"] == [{"name": "Shop Support Desk", "count": 3},
                                               {"name": CLOUD, "count": 1}]
    assert everything["services"] == [{"name": "Checkout", "count": 3}, {"name": "Parcel Tracking", "count": 1}]
    inside = await known_values(config(servicenow_services=["Parcel Tracking"]), limited=True)
    assert inside["assignment_groups"] == [{"name": "Shop Support Desk", "count": 1}]
    outside = await known_values(config(servicenow_services=["Parcel Tracking"]), limited=False)
    assert outside["scanned"] == 4


async def test_known_values_route_is_for_workspace_admins_only(db, sn):  # noqa: F811
    from app.api.routes.secure_work_servicenow import router
    from app.db import get_db
    from app.services.auth import get_current_user
    from tests.test_jira_task_list_governance import _operator

    sn.data[INCIDENTS_PATH] = [row(1, DESK, "Checkout"), row(2, CLOUD, "Parcel Tracking")]
    project_id, admin = await workspace(db, servicenow_assignment_groups=[CLOUD])
    member = await _operator(db)
    db.add(UserProject(user_id=member.id, project_id=project_id, role="member"))
    await db.commit()
    app = FastAPI()
    app.include_router(router)
    state = {"user": member}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    route = f"/api/v1/secure-work/servicenow-intake/{project_id}/limit-values"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sn.test") as client:
        assert (await client.get(route)).status_code == 403
        state["user"] = admin
        answer = await client.get(route)
        assert answer.status_code == 200
        assert answer.json()["services"] == [{"name": "Parcel Tracking", "count": 1}]  # inside the connector's limit
        assert (await client.get(route, params={"table": "problem"})).status_code == 409
