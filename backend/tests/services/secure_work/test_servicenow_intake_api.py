"""Contract: the ServiceNow intake API and the prepared work-note action, which is off by default and posts
only a confirmed summary after the secret scan."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.secure_work.secure_work_servicenow import router
from app.db import get_db
from app.models import AuditLog, UserProject, WorkItem
from app.services.auth import get_current_user
from app.services.connector_auth.atlassian_modes import AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import validate_auth_config
from app.services.secure_work.servicenow.intake import put_intake, run_intake
from app.services.secure_work.servicenow.worknote import send_worknote, worknote_text
from tests.servicenow_intake_support import INCIDENTS_PATH, WritingStub, incident, stub, workspace
from tests.servicenow_stub_support import PASSWORD, config, sys_id
from tests.tools.jira_impl.test_jira_task_list_governance import _operator

API = "/api/v1/secure-work"
SUMMARY = "Likely cause: the batch host ran out of disk space."
NOTE = {"at": "2026-10-06T10:00:00", "kind": "analysis", "author_type": "agent", "summary": SUMMARY,
        "note": f"{SUMMARY}\n\nEvidence: vendor manual page 12, helm values L3-9."}


@pytest.fixture
def sn(monkeypatch):
    instance = WritingStub(incidents=0, changes=0)
    instance.data[INCIDENTS_PATH] = [incident(1, "New"), incident(2, "In Progress")]
    yield from stub(monkeypatch, instance)


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sn.test") as client:
        yield client, state


async def test_members_read_and_admins_preview_and_sync(db, sn, api):
    client, state = api
    project_id, admin = await workspace(db)
    member = await _operator(db)
    db.add(UserProject(user_id=member.id, project_id=project_id, role="member"))
    await db.commit()
    route = f"{API}/servicenow-intake/{project_id}"

    state["user"] = member
    read = await client.get(route)
    assert read.status_code == 200 and read.json()["configured"] is False
    assert read.json()["intake"]["tables"] == ["incident"]
    assert (await client.post(f"{route}/sync")).status_code == 403

    state["user"] = admin
    unconfigured = await client.post(f"{route}/preview")
    assert unconfigured.status_code == 409 and unconfigured.json()["detail"]["code"] == "servicenow_intake_not_configured"
    saved = await put_intake(db, project_id=project_id, user=admin, payload={
        "connection_id": "default", "tables": ["incident"], "schedule": {"preset": "manual"}})
    await db.commit()
    assert (await client.get(route)).json()["configured"] is True
    preview = await client.post(f"{route}/preview")
    assert preview.status_code == 200 and preview.json()["summary"]["imported"] == 2
    assert (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all() == []
    synced = await client.post(f"{route}/sync")
    assert synced.status_code == 200 and synced.json()["summary"]["imported"] == 2
    state["user"] = member
    runs = (await client.get(f"{route}/runs")).json()["runs"]
    assert [run["mode"] for run in runs] == ["sync", "dry_run"]
    audit = (await db.execute(select(AuditLog.action).where(AuditLog.resource_id == saved.id))).scalars()
    assert {"secure_work.servicenow_intake.configured", "secure_work.servicenow_intake.synced"} <= set(audit)


async def test_an_unknown_workspace_and_a_missing_connection_are_coded(db, sn, api):
    client, state = api
    project_id, admin = await workspace(db, servicenow_url="")
    state["user"] = admin
    assert (await client.get(f"{API}/servicenow-intake/{uuid.uuid4()}")).status_code == 404
    await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await db.commit()
    failed = await client.post(f"{API}/servicenow-intake/{project_id}/preview")
    assert failed.status_code == 409 and failed.json()["detail"]["code"] == "servicenow_connection_not_configured"


async def _analysed_item(db, **connection) -> tuple[WorkItem, object]:
    project_id, admin = await workspace(db, **connection)
    row = await put_intake(db, project_id=project_id, payload={"connection_id": "default"}, user=admin)
    await run_intake(db, row=row, user=admin, dry_run=False)
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "INC0000001",
                                                    WorkItem.project_id == project_id))).scalar_one()
    item.source_fields_json = {**item.source_fields_json, "platform_notes": [dict(NOTE)]}
    await db.commit()
    return item, admin


def _sent(admin) -> str:
    return f"{SUMMARY}\n\n— Written by an agent (octryx) — responsible: {admin.display_name}."


async def test_work_notes_are_off_by_default(db, sn, api):
    client, state = api
    item, admin = await _analysed_item(db)
    state["user"] = admin
    refused = await client.post(f"{API}/work-items/{item.id}/servicenow-worknote", json={"confirm": True})
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"state": "disabled", "code": "servicenow_worknote_disabled",
                                        "message": refused.json()["detail"]["message"]}
    assert sn.writes == []


async def test_a_confirmed_action_posts_the_summary_once_through_the_table_api(db, sn, api):
    client, state = api
    item, admin = await _analysed_item(db, servicenow_worknote_mode="table_api")
    state["user"] = admin
    route = f"{API}/work-items/{item.id}/servicenow-worknote"
    preview = await client.post(route, json={})
    assert preview.json() == {"state": "needs_confirmation", "preview": {
        "mode": "table_api", "table": "incident", "number": "INC0000001", "text": _sent(admin)}}
    assert sn.writes == [], "nothing is sent without the confirmation"
    posted = await client.post(route, json={"confirm": True, "note_at": NOTE["at"]})
    assert posted.status_code == 200 and posted.json()["state"] == "posted"
    assert sn.writes == [("PATCH", f"/api/now/table/incident/{sys_id(1)}", {"work_notes": _sent(admin)})]
    await db.refresh(item)
    assert item.source_fields_json["platform_notes"][0]["worknote_posted_at"]
    again = await client.post(route, json={"confirm": True})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "servicenow_worknote_already_posted"
    assert len(sn.writes) == 1
    audit = (await db.execute(select(AuditLog.details).where(
        AuditLog.action == "secure_work.servicenow_worknote.posted"))).scalars().all()
    assert audit == [{"mode": "table_api", "table": "incident", "chars": len(_sent(admin))}]


async def test_the_scripted_post_target_and_its_failure(db, sn, api):
    client, state = api
    item, admin = await _analysed_item(db, servicenow_worknote_mode="scripted_post",
                                       servicenow_worknote_path="/api/x_test/integration/worknotes")
    state["user"] = admin
    route = f"{API}/work-items/{item.id}/servicenow-worknote"
    sn.write_status = 500
    failed = await client.post(route, json={"confirm": True})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "servicenow_worknote_failed"
    await db.refresh(item)
    assert "worknote_posted_at" not in item.source_fields_json["platform_notes"][0]
    sn.write_status = 201
    assert (await client.post(route, json={"confirm": True})).json()["state"] == "posted"
    method, path, body = sn.writes[-1]
    assert (method, path) == ("POST", "/api/x_test/integration/worknotes")
    assert body == {"table": "incident", "sys_id": sys_id(1), "number": "INC0000001", "work_notes": _sent(admin)}


async def test_a_concurrent_confirmation_is_refused_by_the_claim_committed_before_the_call(db, sn, api):
    client, state = api
    item, admin = await _analysed_item(db, servicenow_worknote_mode="table_api")
    state["user"] = admin
    other = AsyncSession(bind=db.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    stale = await other.get(WorkItem, item.id)
    assert "worknote_posted_at" not in stale.source_fields_json["platform_notes"][0]
    concurrent: list = []
    handle = sn.handle

    async def during_the_call(request):
        if request.method == "PATCH" and not concurrent:
            claimed = (await other.execute(select(WorkItem.source_fields_json).where(WorkItem.id == item.id))).scalar_one()
            assert claimed["platform_notes"][0]["worknote_posted_at"], "the claim is committed before the call"
            with pytest.raises(HTTPException) as refused:
                await send_worknote(other, item=stale, user=admin, note_at=None, confirm=True)
            concurrent.append(refused.value.detail["code"])
        return await handle(request)

    sn.handle = during_the_call
    posted = await client.post(f"{API}/work-items/{item.id}/servicenow-worknote", json={"confirm": True})
    await other.close()
    assert posted.json()["state"] == "posted"
    assert concurrent == ["servicenow_worknote_already_posted"] and len(sn.writes) == 1


async def test_a_secret_never_leaves_and_only_an_analysis_note_is_sent(db, sn, api):
    client, state = api
    item, admin = await _analysed_item(db, servicenow_worknote_mode="table_api")
    state["user"] = admin
    route = f"{API}/work-items/{item.id}/servicenow-worknote"
    secret = {**NOTE, "summary": "Use token ghp_" + "A" * 36 + " to reproduce."}
    item.source_fields_json = {**item.source_fields_json, "platform_notes": [secret]}
    await db.commit()
    refused = await client.post(route, json={"confirm": True})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "servicenow_worknote_secret_detected"
    item.source_fields_json = {**item.source_fields_json, "platform_notes": [{"note": "a progress note"}]}
    await db.commit()
    missing = await client.post(route, json={"confirm": True})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "servicenow_worknote_no_analysis_note"
    assert sn.writes == [] and PASSWORD not in str(refused.json())


async def test_a_jira_item_has_no_servicenow_work_note(db, sn, api):
    client, state = api
    project_id, admin = await workspace(db, servicenow_worknote_mode="table_api")
    item = WorkItem(project_id=project_id, source_type="jira", source_key="BRD-1", title="BRD-1")
    db.add(item)
    await db.commit()
    state["user"] = admin
    refused = await client.post(f"{API}/work-items/{item.id}/servicenow-worknote", json={"confirm": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "servicenow_worknote_not_a_servicenow_item"


def test_the_summary_is_the_analysis_summary_or_its_first_paragraph():
    assert worknote_text(NOTE) == SUMMARY
    assert worknote_text({"note": "First paragraph.\n\nEvidence: raw"}) == "First paragraph."
    assert len(worknote_text({"summary": "x" * 9000})) == 4000


@pytest.mark.parametrize(("fields", "ok"), [
    ({}, True),
    ({"servicenow_worknote_mode": "off"}, True),
    ({"servicenow_worknote_mode": "table_api"}, True),
    ({"servicenow_worknote_mode": "scripted_post", "servicenow_worknote_path": "/api/x/notes"}, True),
    ({"servicenow_worknote_mode": "scripted_post"}, False),
    ({"servicenow_worknote_mode": "scripted_post", "servicenow_worknote_path": "https://h.test/api/x"}, False),
    ({"servicenow_worknote_mode": "table_api", "servicenow_worknote_path": "/api/../x"}, False),
    ({"servicenow_worknote_mode": "email"}, False),
])
def test_the_worknote_settings_are_validated(fields, ok):
    candidate = {**config(), **fields}
    if ok:
        validate_auth_config("servicenow", candidate)
    else:
        with pytest.raises(AtlassianAuthConfigError):
            validate_auth_config("servicenow", candidate)
