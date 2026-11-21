"""Work item status precedence at the Jira sync, the filter fall-out, and the explicit Close action.

- a terminal Jira state (statusCategory ``done``) wins even against a locally transitioned item;
- an item a *complete* sync no longer returns is closed and marked ``removed_from_source_filter``; a limited
  or request-supplied (unflagged) result never concludes that;
- ``POST /work-items/{id}/close`` transitions Jira into a done-category status when write-back is configured
  (``source_transition``), closes locally otherwise (``local_only``), and a refused transition is a coded
  refusal that leaves the item open.

No network: ``httpx.MockTransport`` and fakes only.
"""

from __future__ import annotations

import json
import uuid

import httpx
from sqlalchemy import select

import app.services.secure_work.jira.jira_sync_source as jira_sync_source
from app.models import AuditLog, Project, WorkItem, WorkItemStateEvent
from app.services.secure_work.jira.jira_item_upsert import fall_out_check
from app.services.secure_work.jira.jira_state_sync import resolve_transition
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import dc_config, use_transport, workspace_jira

API = "/api/v1/secure-work"
DONE = {"name": "Done", "statusCategory": {"key": "done"}}
IN_PROGRESS = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
OPEN = {"name": "Open", "statusCategory": {"key": "new"}}


def _issue(key: str, status: dict) -> dict:
    return {"id": f"id-{key}", "key": key,
            "fields": {"project": {"key": key.split("-")[0]}, "summary": f"Issue {key}", "status": status,
                       "updated": "2026-11-01T10:00:00Z"}}


async def _intake(db) -> str:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": f"intake-{uuid.uuid4().hex[:6]}", "project_id": project.id, "filters": {"project_keys": ["ACME"]}})
    return created["id"]


def _fetch_returning(issues: list[dict], *, complete: bool = True):
    async def fake_fetch(db_arg, *, config, jql, limit):
        return {"configured": True, "issues": issues, "source_count": len(issues) + (0 if complete else 50),
                "source_complete": complete, "metadata": {"source": "test_connector", "returned": len(issues)}}
    return fake_fetch


FULL = {"full_resync": True}  # only a full run may conclude an item left the filter (sync_window)


async def _sync(db, config_id, payload=None) -> dict:
    return (await run_jira_intake(db, config_id, payload))["sync_run"]["summary"]


async def _item(db, key: str) -> WorkItem:
    stmt = select(WorkItem).where(WorkItem.source_key == key).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _events(db, item_id: str) -> list[WorkItemStateEvent]:
    return list((await db.execute(select(WorkItemStateEvent).where(WorkItemStateEvent.work_item_id == item_id)
                                  .order_by(WorkItemStateEvent.created_at))).scalars())


# --- 1. sync precedence and the filter fall-out -------------------------------------------------------------


async def test_done_at_the_source_wins_against_a_locally_transitioned_item(client, auth_headers, db, monkeypatch):
    config_id = await _intake(db)
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-145", IN_PROGRESS), _issue("ACME-146", IN_PROGRESS)]))
    await _sync(db, config_id)
    admin_id = await _admin_id(db)
    for key in ("ACME-145", "ACME-146"):  # the platform lifecycle moved ahead of Jira
        item = await _item(db, key)
        db.add(WorkItemStateEvent(work_item_id=item.id, from_state=item.work_state, to_state="review",
                                  actor_id=admin_id, source="manual", dry_run=False))
        item.work_state = "review"
    await db.commit()

    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-145", DONE), _issue("ACME-146", IN_PROGRESS)]))
    summary = await _sync(db, config_id)

    closed, protected = await _item(db, "ACME-145"), await _item(db, "ACME-146")
    assert (closed.work_state, closed.source_status) == ("done", "Done")
    assert protected.work_state == "review", "an open source state still never regresses the local lifecycle"
    assert summary["closed_at_source"] == 1
    event = (await _events(db, closed.id))[-1]
    assert (event.source, event.from_state, event.to_state) == ("jira_sync", "review", "done")
    assert event.reason.startswith("closed_at_source")
    assert event.jira_sync_preview_json["overrode_local_transition"] is True

    # Reopened in Jira: the sync's own event never protects, the item follows the source again.
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-145", IN_PROGRESS), _issue("ACME-146", IN_PROGRESS)]))
    await _sync(db, config_id)
    assert (await _item(db, "ACME-145")).work_state == "development"


async def _admin_id(db) -> str:
    from app.models import User

    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def test_a_complete_sync_closes_what_fell_out_of_the_filter(client, auth_headers, db, monkeypatch):
    config_id = await _intake(db)
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-1", OPEN), _issue("ACME-2", OPEN)]))
    await _sync(db, config_id)

    # Partial result (paging left issues behind): nothing may be concluded about the absent one.
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-1", OPEN)], complete=False))
    partial = await _sync(db, config_id, FULL)
    assert partial["removed_from_source_filter"] == 0
    assert partial["removed_from_source_filter_skipped_reason"] == "source_result_incomplete"
    untouched = await _item(db, "ACME-2")
    assert (untouched.work_state, untouched.sync_state) == ("intake", "imported")

    # Complete result (all pages) without the issue: closed with an explaining event, once.
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-1", OPEN)]))
    full = await _sync(db, config_id, FULL)
    gone = await _item(db, "ACME-2")
    assert full["removed_from_source_filter"] == 1
    assert (gone.work_state, gone.sync_state) == ("done", "removed_from_source_filter")
    event = (await _events(db, gone.id))[-1]
    assert (event.source, event.to_state, event.from_state) == ("jira_sync", "done", "intake")
    assert event.reason.startswith("removed_from_source_filter")
    assert (await _item(db, "ACME-1")).work_state == "intake"
    again = await _sync(db, config_id, FULL)
    assert again["removed_from_source_filter"] == 0 and len(await _events(db, gone.id)) == 1

    # Back in the filter: it takes its source state again.
    monkeypatch.setattr(jira_sync_source, "fetch_jira_issues_for_sync",
                        _fetch_returning([_issue("ACME-1", OPEN), _issue("ACME-2", IN_PROGRESS)]))
    await _sync(db, config_id)
    back = await _item(db, "ACME-2")
    assert (back.work_state, back.sync_state) == ("development", "updated")


async def test_a_limited_or_unflagged_request_result_never_concludes_a_fall_out(client, auth_headers, db, monkeypatch):
    config_id = await _intake(db)
    await _sync(db, config_id, {"issues": [_issue("ACME-7", OPEN), _issue("ACME-8", OPEN)]})
    unflagged = await _sync(db, config_id, {"issues": [_issue("ACME-7", OPEN)]})
    assert unflagged["removed_from_source_filter_skipped_reason"] == "request_payload_not_authoritative"
    limited = await _sync(db, config_id, {"limit": 1, "mark_removed_from_filter": True,
                                                            "issues": [_issue("ACME-7", OPEN)]})
    assert limited["removed_from_source_filter_skipped_reason"] == "source_result_incomplete"
    assert (await _item(db, "ACME-8")).work_state == "intake"


def test_fall_out_check_needs_a_complete_unlimited_result():
    complete = {"source_complete": True, "metadata": {"source": "connector"}}
    assert fall_out_check({}, source=complete, limit=None, matched_count=3) == "apply"
    assert fall_out_check({}, source=complete, limit=1000, matched_count=3) == "apply"
    assert fall_out_check({}, source=complete, limit=2, matched_count=3) == "source_result_incomplete"
    assert fall_out_check({}, source={**complete, "source_complete": False}, limit=None,
                          matched_count=3) == "source_result_incomplete"
    assert fall_out_check({"mark_removed_from_filter": False}, source=complete, limit=None,
                          matched_count=3) == "disabled_by_request"


# --- 2. the Close action -------------------------------------------------------------------------------------


class CloseJira:
    """A Server/DC Jira serving the transitions of one issue; records every request."""

    def __init__(self, transitions: list[dict], *, post_status: int = 204) -> None:
        self.transitions, self.post_status, self.requests = transitions, post_status, []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            self.requests.append({"method": request.method, "path": request.url.path, "body": body})
            if request.url.path.endswith("/transitions"):
                if request.method == "GET":
                    return httpx.Response(200, json={"transitions": self.transitions})
                return httpx.Response(self.post_status)
            return httpx.Response(404, json={"errorMessages": ["not found"]})
        return httpx.MockTransport(handler)

    def posted(self) -> list[dict]:
        return [entry for entry in self.requests if entry["method"] == "POST"]


DONE_OFFER = [{"id": "11", "name": "Start Progress", "to": IN_PROGRESS},
              {"id": "31", "name": "Close Issue", "to": DONE}]


async def _workflow(client, headers, project_id, *, mode: str, done_mapping: dict | None) -> str:
    response = await client.post(f"{API}/workflows", headers=headers, json={
        "name": f"flow-{uuid.uuid4().hex[:6]}", "project_id": project_id, "is_default": True,
        "sync_policy": {"sync_mode": mode}, "mappings": {"done": done_mapping} if done_mapping else {}})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _open_item(db, project_id: str, key: str = "ACME-145") -> str:
    item = WorkItem(project_id=project_id, source_type="jira", source_instance=f"t-{uuid.uuid4().hex[:6]}",
                    source_key=key, title=key, work_state="review", sync_state="imported", source_status="In Progress")
    db.add(item)
    await db.commit()
    return item.id


async def test_close_with_write_back_transitions_jira_into_a_done_status(client, auth_headers, db, monkeypatch):
    jira = CloseJira(DONE_OFFER)
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    await _workflow(client, auth_headers, project_id, mode="execute", done_mapping={"sync_back": True})
    item_id = await _open_item(db, project_id)
    detail = (await client.get(f"{API}/work-items/{item_id}", headers=auth_headers)).json()
    assert (detail["close_mode"], detail["write_back_reason"]) == ("source_transition", None)

    response = await client.post(f"{API}/work-items/{item_id}/close", headers=auth_headers, json={"reason": "fixed"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["closed"], body["mode"], body["work_state"]) == (True, "source_transition", "done")
    assert body["write_back"] == {"enabled": True, "reason": None}
    assert (body["jira"]["transition_name"], body["jira"]["resulting_status"]) == ("Close Issue", "Done")
    assert body["source_status"] == "Done" and body["event"]["source"] == "close_action"
    assert jira.posted() == [{"method": "POST", "path": "/rest/api/2/issue/ACME-145/transitions",
                              "body": {"transition": {"id": "31"}}}]
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "secure_work.work_item_closed",
                                                     AuditLog.resource_id == item_id))).scalar_one()
    assert audit.details["mode"] == "source_transition"


async def test_close_without_write_back_is_local_only(client, auth_headers, db, monkeypatch):
    jira = CloseJira(DONE_OFFER)
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    await _workflow(client, auth_headers, project_id, mode="dry_run_only", done_mapping={"sync_back": True})
    item_id = await _open_item(db, project_id)
    detail = (await client.get(f"{API}/work-items/{item_id}", headers=auth_headers)).json()
    assert (detail["close_mode"], detail["write_back_reason"]) == ("local_only", "write_back_disabled")

    response = await client.post(f"{API}/work-items/{item_id}/close", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["closed"], body["mode"], body["work_state"]) == (True, "local_only", "done")
    assert body["write_back"] == {"enabled": False, "reason": "write_back_disabled"}
    assert body["jira"] is None and jira.requests == [], "no request reaches Jira"
    assert body["source_status"] == "In Progress"
    again = await client.post(f"{API}/work-items/{item_id}/close", headers=auth_headers, json={})
    assert again.json()["mode"] == "already_closed"


async def test_close_refuses_explicitly_when_jira_offers_no_done_transition(client, auth_headers, db, monkeypatch):
    jira = CloseJira([{"id": "11", "name": "Start Progress", "to": IN_PROGRESS}])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    await _workflow(client, auth_headers, project_id, mode="execute", done_mapping={"sync_back": True})
    item_id = await _open_item(db, project_id)

    response = await client.post(f"{API}/work-items/{item_id}/close", headers=auth_headers, json={})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert (detail["closed"], detail["mode"], detail["code"]) == (False, "source_transition", "transition_not_available")
    assert "Jira offers" in detail["message"]
    assert jira.posted() == []
    item = await _item(db, "ACME-145")
    assert item.work_state == "review", "never a local close instead"
    refused = (await _events(db, item_id))[-1]
    assert (refused.source, refused.jira_sync_preview_json["refusal"]["code"]) == (
        "transition_refused", "transition_not_available")


async def test_close_reports_a_failed_jira_write_as_write_back_failed(client, auth_headers, db, monkeypatch):
    jira = CloseJira(DONE_OFFER, post_status=500)
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    await _workflow(client, auth_headers, project_id, mode="execute",
                    done_mapping={"sync_back": True, "source_transition": "Close Issue"})
    item_id = await _open_item(db, project_id)

    response = await client.post(f"{API}/work-items/{item_id}/close", headers=auth_headers, json={})

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "write_back_failed"
    assert (await _item(db, "ACME-145")).work_state == "review"


def test_done_category_resolution_needs_exactly_one_offer():
    two = [*DONE_OFFER, {"id": "41", "name": "Won't Do", "to": {"name": "Rejected", "statusCategory": {"key": "done"}}}]
    assert resolve_transition(DONE_OFFER, jira_transition=None, jira_status=None, status_category="done")["id"] == "31"
    assert resolve_transition(two, jira_transition=None, jira_status=None, status_category="done") is None
    assert resolve_transition(two, jira_transition="Won't Do", jira_status=None, status_category="done")["id"] == "41"
