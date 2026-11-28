"""The Jira intake writes only what changed, and remembers which REST API version an instance answers."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

import app.services.connector_test.collab as collab_module
import app.services.secure_work.jira.jira_connector as connector_module
import app.services.secure_work.jira.jira_item_upsert as upsert_module
from app.models import Project, WorkItem
from app.tools.jira_impl._jira_api_versions import api_versions, instance_key, remember_api_version
from tests.jira_intake_support import create_jira_intake, run_jira_intake

DC_URL = "https://jira.example.com/jira"
OLD = datetime(2026, 1, 1, 12, 0, 0)


def _issue(key: str, *, summary: str, status: str = "To Do") -> dict:
    return {
        "id": f"id-{key}",
        "key": key,
        "fields": {
            "project": {"key": "OCX"},
            "summary": summary,
            "description": f"Description for {key}",
            "issuetype": {"name": "Story"},
            "status": {"name": status, "statusCategory": {"key": "new"}},
            "priority": {"name": "High"},
            "assignee": {"name": "alice", "displayName": "Alice Example"},
            "labels": ["secure-work"],
            "comment": {"comments": [{"id": "1", "author": {"name": "a"}, "body": "hi",
                                      "created": "2026-06-19T10:00:00.000+0200"}], "total": 1},
            "created": "2026-06-19T09:00:00.000+0200",
            "updated": "2026-06-20T10:00:00.000+0200",
        },
    }


async def _sync(db, config_id: str, issues: list[dict]) -> dict:
    return (await run_jira_intake(db, config_id, {"issues": issues}))["sync_run"]["summary"]


async def _items(db, config_id: str) -> dict[str, WorkItem]:
    db.expire_all()
    rows = (await db.execute(select(WorkItem).where(WorkItem.sync_config_id == config_id))).scalars()
    return {row.source_key: row for row in rows}


@pytest.mark.asyncio
async def test_an_unchanged_item_is_not_written_again(client, auth_headers, db, monkeypatch):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Write avoidance", "project_id": project.id, "filters": {"project_keys": ["OCX"]}})
    config_id = created["id"]
    issues = [_issue("OCX-10", summary="First"), _issue("OCX-11", summary="Second")]

    first = await _sync(db, config_id, issues)
    assert (first["imported"], first["updated"], first["unchanged"]) == (2, 0, 0)
    second = await _sync(db, config_id, issues)
    assert (second["imported"], second["updated"], second["unchanged"]) == (0, 0, 2)
    assert {row.sync_state for row in (await _items(db, config_id)).values()} == {"unchanged"}

    # Mark the rows so any later write shows; then a run over the same issues must leave them alone.
    for row in (await _items(db, config_id)).values():
        row.synced_at = OLD
        row.updated_at = OLD
    await db.commit()
    lookups: list[str] = []
    real_lookup = upsert_module.work_state_is_locally_transitioned

    async def counting_lookup(session, item):
        lookups.append(item.source_key)
        return await real_lookup(session, item)

    monkeypatch.setattr(upsert_module, "work_state_is_locally_transitioned", counting_lookup)
    third = await _sync(db, config_id, issues)

    assert (third["imported"], third["updated"], third["unchanged"]) == (0, 0, 2)
    rows = await _items(db, config_id)
    assert {(row.synced_at, row.updated_at) for row in rows.values()} == {(OLD, OLD)}
    assert lookups == [], "an unchanged state needs no lookup of local transitions"

    fourth = await _sync(db, config_id,
                         [_issue("OCX-10", summary="First, renamed"), _issue("OCX-11", summary="Second")])
    assert (fourth["updated"], fourth["unchanged"]) == (1, 1)
    rows = await _items(db, config_id)
    assert rows["OCX-10"].title == "First, renamed"
    assert rows["OCX-10"].sync_state == "updated" and rows["OCX-10"].synced_at > OLD
    assert (rows["OCX-11"].synced_at, rows["OCX-11"].updated_at) == (OLD, OLD)

    # The run after a change records it as unchanged again (one write), then nothing.
    fifth = await _sync(db, config_id,
                        [_issue("OCX-10", summary="First, renamed"), _issue("OCX-11", summary="Second")])
    assert (fifth["updated"], fifth["unchanged"]) == (0, 2)
    assert (await _items(db, config_id))["OCX-10"].sync_state == "unchanged"


@pytest.mark.asyncio
async def test_a_duplicate_issue_in_one_result_is_imported_once(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Duplicate keys", "project_id": project.id, "filters": {"project_keys": ["OCX"]}})
    config_id = created["id"]

    summary = await _sync(db, config_id,
                          [_issue("OCX-20", summary="Once"), _issue("OCX-20", summary="Once")])

    assert (summary["imported"], summary["unchanged"]) == (1, 1)
    assert list(await _items(db, config_id)) == ["OCX-20"]


def _dc_transport(seen: list[str], *, v3_exists: bool = False, v2_exists: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if "/rest/api/3/" in request.url.path and not v3_exists:
            return httpx.Response(404, json={})
        if "/rest/api/2/" in request.url.path and not v2_exists:
            return httpx.Response(404, json={})
        if request.url.path.endswith("/myself"):
            return httpx.Response(200, json={"name": "svc"})
        start = int(request.url.params.get("startAt", "0"))
        issues = [{"id": str(n), "key": f"OPS-{n}", "fields": {"summary": "s"}} for n in range(start, min(start + 2, 3))]
        return httpx.Response(200, json={"issues": issues, "total": 3})

    return httpx.MockTransport(handler)


def _sync_config():
    from types import SimpleNamespace

    return SimpleNamespace(project_id="p1", id="c1", connection_id="jira", source_instance="dc",
                           sync_options_json={}, field_mapping_json={})


async def _fetch(monkeypatch, transport) -> dict:
    async def config(_db, _config):
        return {"jira_url": DC_URL, "jira_username": "u", "jira_password": "p", "jira_auth_mode": "basic"}

    monkeypatch.setattr(connector_module, "_resolve_jira_connector_config", config)
    monkeypatch.setattr(connector_module, "egress_transport", lambda *_args, **_kwargs: transport)
    return await connector_module.fetch_jira_issues_for_sync(None, config=_sync_config(), jql="project = OPS", limit=50)


@pytest.mark.asyncio
async def test_a_data_center_instance_is_asked_on_v2_after_the_first_404(monkeypatch):
    seen: list[str] = []
    transport = _dc_transport(seen)

    first = await _fetch(monkeypatch, transport)
    assert [issue["key"] for issue in first["issues"]] == ["OPS-0", "OPS-1", "OPS-2"]
    assert first["metadata"]["api_version"] == "2"
    assert seen == ["/jira/rest/api/3/search", "/jira/rest/api/2/search", "/jira/rest/api/2/search"]

    seen.clear()
    second = await _fetch(monkeypatch, transport)
    assert second["source_complete"] is True and second["metadata"]["api_version"] == "2"
    assert seen == ["/jira/rest/api/2/search", "/jira/rest/api/2/search"], "no v3 request"


@pytest.mark.asyncio
async def test_a_remembered_version_that_stops_answering_falls_back_and_is_replaced(monkeypatch):
    remember_api_version(DC_URL, "2")
    seen: list[str] = []

    result = await _fetch(monkeypatch, _dc_transport(seen, v3_exists=True, v2_exists=False))

    assert result["metadata"]["api_version"] == "3"
    assert seen[:2] == ["/jira/rest/api/2/search", "/jira/rest/api/3/search"]
    assert api_versions(DC_URL) == ("3", "2")


@pytest.mark.asyncio
async def test_the_connection_check_remembers_the_version_too(monkeypatch):
    seen: list[str] = []
    transport = _dc_transport(seen)
    monkeypatch.setattr(collab_module, "egress_transport", lambda *_args, **_kwargs: transport)
    config = {"jira_url": DC_URL, "jira_username": "u", "jira_password": "p", "jira_auth_mode": "basic"}

    first = await collab_module.test_jira_connection(config, httpx_module=httpx)
    second = await collab_module.test_jira_connection(config, httpx_module=httpx)

    assert first["ok"] is True and second["ok"] is True
    assert "REST API 2" in second["summary"]
    assert seen == ["/jira/rest/api/3/myself", "/jira/rest/api/2/myself", "/jira/rest/api/2/myself"]


def test_the_instance_key_ignores_case_of_scheme_and_host_and_a_trailing_slash():
    assert instance_key("HTTPS://Jira.Example.com/jira/") == instance_key("https://jira.example.com/jira")
    assert instance_key("https://jira.example.com/Jira") != instance_key("https://jira.example.com/jira")
    remember_api_version("https://jira.example.com/jira/", "2")
    assert api_versions("HTTPS://JIRA.example.com/jira") == ("2", "3")
    assert api_versions("https://other.example.com") == ("3", "2")
