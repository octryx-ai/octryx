"""Syncs are incremental so a one-minute schedule works; one run per configuration at a time."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

import app.services.secure_work.jira.jira_sync as jira_sync
from app.models import Project, WorkItem, WorkItemSyncConfig, WorkItemSyncRun
from app.services.secure_work.intake.schedule import PRESET_CRONS
from app.services.secure_work.sync_window import acquire_sync_lease, incremental_jql
from app.time_utils import utc_now
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.test_jira_sync_write_avoidance import _issue


class FakeJira:
    """The source behind ``_resolve_source_issues``: each call and its JQL, the issues it answers."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.issues: list[dict] = []

    async def __call__(self, db, *, config, payload, limit, query_preview):
        del db, config, payload, limit
        self.calls.append(query_preview)
        return {"configured": True, "issues": list(self.issues), "source_count": len(self.issues),
                "complete": True, "metadata": {"source": "jira"}}


async def _config(db) -> str:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    created = await create_jira_intake(db, {
        "name": "Incremental", "project_id": project.id,
        "filters": {"project_keys": ["OCX"], "statuses": ["To Do", "In Progress"]}})
    return created["id"]


async def _sync(db, config_id: str, **extra) -> dict:
    return await run_jira_intake(db, config_id, extra)


@pytest.mark.asyncio
async def test_the_first_run_is_full_then_only_changes_in_any_status_come_and_a_closed_issue_leaves(
        client, auth_headers, db, monkeypatch):
    fake = FakeJira()
    monkeypatch.setattr(jira_sync, "_resolve_source_issues", fake)
    config_id = await _config(db)
    fake.issues = [_issue("OCX-1", summary="One"), _issue("OCX-2", summary="Two")]
    first = (await _sync(db, config_id))["sync_run"]["summary"]
    assert (first["window"], first["full_reason"], first["imported"]) == ("full", "first_run", 2)
    assert "updated >=" not in fake.calls[0]

    fake.calls.clear()
    fake.issues = []
    quiet = (await _sync(db, config_id))["sync_run"]["summary"]
    assert len(fake.calls) == 1 and quiet["window"] == "incremental" and quiet["imported"] == 0
    assert "updated >= -" in fake.calls[0] and "status" not in fake.calls[0].lower()  # every status
    assert int(fake.calls[0].split("updated >= -")[1].split("m")[0]) >= 6  # the window plus 5 minutes overlap
    assert len(await _items(db, config_id)) == 2  # nothing unseen was concluded to have left

    fake.issues = [_issue("OCX-2", summary="Two", status="Done")]  # closed: no longer in the intake's statuses
    closed = (await _sync(db, config_id))["sync_run"]["summary"]
    assert closed["left_filter"] == 1
    items = await _items(db, config_id)
    assert items["OCX-2"].sync_state == "removed_from_source_filter" and items["OCX-1"].sync_state != (
        "removed_from_source_filter")

    fake.calls.clear()
    full = (await _sync(db, config_id, full_resync=True))["sync_run"]["summary"]
    assert full["window"] == "full" and "updated >=" not in fake.calls[0]


async def _items(db, config_id: str) -> dict[str, WorkItem]:
    db.expire_all()
    rows = (await db.execute(select(WorkItem).where(WorkItem.sync_config_id == config_id))).scalars()
    return {row.source_key: row for row in rows}


@pytest.mark.asyncio
async def test_a_second_start_while_a_run_holds_the_lease_is_skipped_and_an_expired_lease_is_free(
        client, auth_headers, db, monkeypatch):
    fake = FakeJira()
    monkeypatch.setattr(jira_sync, "_resolve_source_issues", fake)
    config_id = await _config(db)
    assert await acquire_sync_lease(db, config_id)  # a run is going
    skipped = await _sync(db, config_id)
    assert skipped["skipped"] == "run_in_progress" and skipped["sync_run"]["status"] == "skipped"
    assert fake.calls == []
    statuses = [row.status for row in (await db.execute(select(WorkItemSyncRun).where(
        WorkItemSyncRun.sync_config_id == config_id))).scalars()]
    assert statuses == ["skipped"]

    config = await db.get(WorkItemSyncConfig, config_id)
    config.run_lease_until = utc_now() - timedelta(minutes=1)  # the run crashed; its lease expired
    await db.commit()
    ran = await _sync(db, config_id)
    assert ran["sync_run"]["status"] == "completed" and len(fake.calls) == 1
    db.expire_all()
    assert (await db.get(WorkItemSyncConfig, config_id)).run_lease_until is None  # released after the run


def test_every_minute_is_a_preset_and_a_custom_jql_keeps_its_own_clauses():
    assert PRESET_CRONS["every_minute"] == "* * * * *"
    assert incremental_jql({"jql": "project = OCX ORDER BY created ASC"}, 7) == (
        "(project = OCX) AND updated >= -7m ORDER BY updated DESC")


@pytest.mark.asyncio
async def test_sync_runs_are_counted_in_memory_by_window_and_outcome(client, auth_headers, db, monkeypatch):
    from app.services.observability import sync_metrics

    sync_metrics.reset()
    fake = FakeJira()
    monkeypatch.setattr(jira_sync, "_resolve_source_issues", fake)
    config_id = await _config(db)
    fake.issues = [_issue("OCX-7", summary="Seven")]
    await _sync(db, config_id)
    assert await acquire_sync_lease(db, config_id)
    await _sync(db, config_id)
    lines = sync_metrics.render()
    assert 'octryx_sync_runs_total{kind="jira",window="full",outcome="completed"} 1' in lines
    assert 'octryx_sync_runs_total{kind="jira",window="none",outcome="skipped"} 1' in lines
    assert 'octryx_sync_items_total{kind="jira",window="full"} 1' in lines
    sync_metrics.reset()
