"""Fetching Jira issues through the configured connector: sprint fields, pagination, malformed issues and
unmapped statuses."""

import pytest
from sqlalchemy import select

import app.services.secure_work.jira.jira_connector as jira_connector
from app.models import BuiltInToolConfig, Project, WorkItem
from tests.jira_intake_support import create_jira_intake, run_jira_intake, update_jira_intake
from tests.secure_work_jira_sync_support import _issue


@pytest.mark.asyncio
async def test_jira_sync_maps_configured_sprint_custom_field(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders custom sprint field",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
        "field_mapping": {"sprint_field": "customfield_10020"},
    })
    config_id = create_response["id"]
    issue = _issue("OCX-203", summary="Custom sprint field task")
    issue["fields"].pop("sprint")
    issue["fields"]["customfield_10020"] = [
        {"id": 903, "name": "Acme Orders Sprint 93", "state": "active"},
    ]

    await run_jira_intake(db, config_id, {"issues": [issue]})

    response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={config_id}&sprint_id=903",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["source_key"] for item in items] == ["OCX-203"]
    assert items[0]["sprint"]["name"] == "Acme Orders Sprint 93"


@pytest.mark.asyncio
async def test_jira_sync_fetches_issues_from_configured_connector(client, auth_headers, db, monkeypatch):
    async def fake_jira_get(client, jira_url, path, *, headers, params=None):
        assert jira_url == "https://jira.example.test"
        assert path == "/search"
        assert headers["Authorization"].startswith("Basic ")
        assert params["jql"].startswith('project in ("OCX")')
        assert "project" in params["fields"].split(",")
        return {"total": 1, "issues": [_issue("OCX-20", summary="Connector backed import")]}, "2"

    monkeypatch.setattr(jira_connector, "_jira_api_get", fake_jira_get)
    db.add(
        BuiltInToolConfig(
            tool_name="jira",
            project_id=None,
            config={
                "jira_auth_mode": "basic",
                "jira_url": "https://jira.example.test",
                "jira_username": "user",
                "jira_password": "pass",
            },
            is_active=True,
        )
    )
    await db.flush()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Connector-backed Jira intake",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
    })

    payload = await run_jira_intake(db, create_response["id"])
    summary = payload["sync_run"]["summary"]
    assert summary["source"]["connector"] == "default"  # the intake's connection
    assert summary["source"].get("api_version") == "2", summary
    assert summary["total_source"] == 1
    assert summary["imported"] == 1
    assert payload["items"][0]["source_key"] == "OCX-20"
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-20"))).scalar_one()
    assert item.source_url == "https://jira.example.test/browse/OCX-20"


@pytest.mark.asyncio
async def test_jira_sync_paginates_connector_results_above_one_hundred(client, auth_headers, db, monkeypatch):
    starts: list[int] = []

    async def fake_jira_get(client, jira_url, path, *, headers, params=None):
        start_at = int(params["startAt"])
        max_results = int(params["maxResults"])
        starts.append(start_at)
        assert max_results <= 100
        issues = [
            _issue(f"OCX-PAGE-{index}", summary=f"Paged connector import {index}")
            for index in range(start_at, min(start_at + max_results, 300))
        ]
        return {"total": 300, "issues": issues}, "2"

    monkeypatch.setattr(jira_connector, "_jira_api_get", fake_jira_get)
    db.add(
        BuiltInToolConfig(
            tool_name="jira",
            project_id=None,
            config={
                "jira_auth_mode": "basic",
                "jira_url": "https://jira.example.test",
                "jira_username": "user",
                "jira_password": "pass",
            },
            is_active=True,
        )
    )
    await db.flush()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Connector-backed Jira paged intake",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
        "sync_options": {"manual_limit": 250},
    })

    summary = (await run_jira_intake(db, create_response["id"]))["sync_run"]["summary"]
    assert starts == [0, 100, 200]
    assert summary["total_source"] == 300
    assert summary["total_valid"] == 250
    assert summary["imported"] == 250
    assert summary["source"]["requested_limit"] == 250
    assert summary["source"]["returned"] == 250
    assert summary["source_complete"] is False
    rows = (
        await db.execute(select(WorkItem).where(WorkItem.source_key.like("OCX-PAGE-%")))
    ).scalars().all()
    assert len(rows) == 250


@pytest.mark.asyncio
async def test_jira_sync_isolates_malformed_issue_and_reports_it(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {"name": "Isolation test", "project_id": project.id})
    config_id = create_response["id"]

    broken = _issue("OCX-901", summary="broken")
    broken.pop("key", None)
    summary = (await run_jira_intake(db, config_id, {"issues": [_issue("OCX-900", summary="healthy"), broken]}))[
        "sync_run"]["summary"]
    assert summary["total_valid"] == 1
    assert summary["mapping_error_count"] == 1
    assert summary["mapping_errors"][0]["issue"] == "?"
    persisted = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-900"))).scalar_one_or_none()
    assert persisted is not None


@pytest.mark.asyncio
async def test_jira_sync_reports_unmapped_statuses(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {"name": "Unmapped status test", "project_id": project.id})
    config_id = create_response["id"]

    odd = {"issues": [_issue("OCX-910", summary="odd status", status="Waiting for Vendor")]}
    summary = (await run_jira_intake(db, config_id, odd))["sync_run"]["summary"]
    assert summary["unmapped_statuses"] == {"Waiting for Vendor": 1}
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-910"))).scalar_one()
    assert item.work_state == "intake"

    await update_jira_intake(db, config_id,
                             {"sync_options": {"status_state_mapping": {"Waiting for Vendor": "blocked"}}})
    summary = (await run_jira_intake(db, config_id, odd))["sync_run"]["summary"]
    assert "unmapped_statuses" not in summary
    await db.refresh(item)
    assert item.work_state == "blocked"
