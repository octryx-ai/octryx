"""Jira sync of work items: dry runs, imports and updates, removal from the filter, state mapping and the OE label."""

import pytest
from sqlalchemy import select

from app.models import Project, WorkItem
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.secure_work_jira_sync_support import _issue


@pytest.mark.asyncio
async def test_jira_sync_config_dry_run_previews_query_without_persisting(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    config = await create_jira_intake(db, {
        "name": "Acme Orders Jira intake",
        "project_id": project.id,
        "connector_name": "jira-cloud",
        "filters": {
            "project_keys": "OCX, BIS",
            "labels_include": ["secure-work"],
            "statuses": ["To Do", "In Progress"],
            "sprint_ids": [42],
            "unknown": "ignored",
        },
        "sync_options": {"manual_limit": 1},
    })
    assert config["filters"] == {
        "project_keys": ["OCX", "BIS"],
        "labels_include": ["secure-work"],
        "statuses": ["To Do", "In Progress"],
        "sprint_ids": ["42"],
    }
    assert config["sync_options"]["manual_limit"] == 1

    dry_run = await run_jira_intake(
        db, config["id"], {"limit": 1, "issues": [_issue("OCX-10", summary="Implement safe branch plan")]},
        dry_run=True)
    summary = dry_run["sync_run"]["summary"]
    assert summary["dry_run"] is True
    assert summary["total_valid"] == 1
    assert "project in" in dry_run["sync_run"]["query_preview"]
    assert dry_run["items"][0]["source_key"] == "OCX-10"

    persisted = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-10"))).scalar_one_or_none()
    assert persisted is None


@pytest.mark.asyncio
async def test_jira_sync_imports_updates_and_marks_removed_from_filter(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders active work",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"], "statuses": ["To Do", "In Progress"]},
    })
    config_id = create_response["id"]

    first_sync_response = await run_jira_intake(db, config_id, {
        "issues": [
            _issue("OCX-10", summary="Implement safe branch plan"),
            _issue("OCX-11", summary="Wire reviewer recommendation"),
            _issue("OPS-1", project_key="OPS", summary="Should stay outside the scoped Jira intake"),
        ]
    })

    first_summary = first_sync_response["sync_run"]["summary"]
    assert first_summary["total_source"] == 3
    assert first_summary["total_after_filter"] == 2
    assert first_summary["imported"] == 2
    assert first_summary["updated"] == 0

    second_sync_response = await run_jira_intake(db, config_id, {
        "mark_removed_from_filter": True,
        "issues": [
            _issue(
                "OCX-10",
                summary="Implement safe branch plan with audit",
                status="In Progress",
                updated="2026-06-20T11:00:00Z",
            )
        ],
    })

    second_summary = second_sync_response["sync_run"]["summary"]
    assert second_summary["updated"] == 1
    assert second_summary["removed_from_source_filter"] == 1

    list_response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={config_id}&limit=10",
        headers=auth_headers,
    )
    assert list_response.status_code == 200, list_response.text
    items = {item["source_key"]: item for item in list_response.json()["items"]}
    assert set(items) == {"OCX-10", "OCX-11"}
    assert items["OCX-10"]["title"] == "Implement safe branch plan with audit"
    assert items["OCX-10"]["source_project_key"] == "OCX"
    assert items["OCX-10"]["source_status"] == "In Progress"
    assert items["OCX-10"]["work_state"] == "development"  # the shared workflow vocabulary
    assert items["OCX-10"]["parent_key"] == "OCX-1"
    assert items["OCX-10"]["epic_key"] == "OCX-EPIC"
    # The list row is lean: watchers and the raw source issue are on the detail read only.
    assert "watchers" not in items["OCX-10"] and "source_fields" not in items["OCX-10"]
    detail = (await client.get(f"/api/v1/secure-work/work-items/{items['OCX-10']['id']}", headers=auth_headers)).json()
    assert detail["watchers"] == ["reviewer-a", "reviewer-b@example.test"]
    assert items["OCX-10"]["assignee"] == "alice"
    assert items["OCX-10"]["fix_versions"] == ["2026.06"]
    assert items["OCX-10"]["sprint"]["id"] == 42
    assert items["OCX-10"]["sprint"]["name"] == "Sprint 42"
    assert items["OCX-10"]["source_created_at"].startswith("2026-06-19T09:00:00")
    assert detail["source_fields"]["raw"]["fields"]["summary"] == "Implement safe branch plan with audit"
    assert items["OCX-11"]["sync_state"] == "removed_from_source_filter"
    assert items["OCX-11"]["work_state"] == "done"  # fell out of a complete filter result: closed, not open forever


@pytest.mark.asyncio
async def test_jira_sync_status_state_mapping_can_override_default_state(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders mapped intake",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
        # A target of the shared vocabulary (an unknown one is a coded 422).
        "sync_options": {"status_state_mapping": {"Requested": "ready_for_plan"}},
    })

    await run_jira_intake(db, create_response["id"],
                          {"issues": [_issue("OCX-42", summary="Mapped requested work", status="Requested")]})

    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-42"))).scalar_one()
    assert item.source_status == "Requested"
    assert item.work_state == "ready_for_plan"


@pytest.mark.asyncio
async def test_jira_sync_octryx_label_marks_work_item_for_octryx(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {
        "name": "Acme Orders OE automation",
        "project_id": project.id,
        "filters": {"project_keys": ["OCX"]},
        "sync_options": {"automation_mode": "direct"},
    })

    await run_jira_intake(db, create_response["id"], {
        "issues": [_issue("OCX-77", summary="Automate this work", labels=["octryx", "acme-orders"])]})

    list_response = await client.get(
        f"/api/v1/secure-work/work-items?sync_config_id={create_response["id"]}&limit=1000",
        headers=auth_headers,
    )
    assert list_response.status_code == 200, list_response.text
    item = list_response.json()["items"][0]
    eligibility = item["automation_eligibility"]
    assert eligibility["requested"] is True
    assert eligibility["can_start"] is True
    assert eligibility["mode"] == "direct"
    assert eligibility["matched_labels"] == ["octryx"]
    assert eligibility["trigger_labels"] == ["octryx"]
    detail = (await client.get(f"/api/v1/secure-work/work-items/{item['id']}", headers=auth_headers)).json()
    assert detail["source_fields"]["automation_policy"]["trigger_labels"] == ["octryx"]


@pytest.mark.asyncio
async def test_dry_run_previews_removed_from_filter(client, auth_headers, db):
    """Dry-run simulates the removal step: it reports which items a real run
    would mark removed_from_source_filter, without touching them."""
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await create_jira_intake(db, {"name": "Removal preview test", "project_id": project.id})
    config_id = create_response["id"]

    await run_jira_intake(db, config_id, {
        "issues": [_issue("OCX-920", summary="will disappear"), _issue("OCX-921", summary="stays")]})
    dry = await run_jira_intake(db, config_id, {"issues": [_issue("OCX-921", summary="stays")],
                                                "mark_removed_from_filter": True}, dry_run=True)
    summary = dry["sync_run"]["summary"]
    assert summary["would_mark_removed"] == ["OCX-920"]
    gone = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-920"))).scalar_one()
    assert gone.sync_state != "removed_from_source_filter"  # dry-run touched nothing
