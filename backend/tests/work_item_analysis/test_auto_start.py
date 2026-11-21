"""Automatic analyses after an intake sync — opt-in, bounded, never failing the sync."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import WorkItem, WorkItemSyncConfig
from app.services.work_item_analysis import auto_start
from app.services.work_item_analysis.auto_start import MAX_PER_SYNC, auto_analyze_after_sync
from app.time_utils import utc_now
from tests.work_item_analysis.support import POLICY, seed_env

ON = {"model_policy": f"{POLICY}@1", "auto_analyze": {"servicenow_new_incidents": True, "jira_label": "OCTRYX"}}


def _record(monkeypatch) -> list[tuple[str, str]]:
    started: list[tuple[str, str]] = []

    async def analyze(db, *, item, user, mode, **_options):
        started.append((item.source_key, mode))
        return {"status": "succeeded", "error_code": None}

    monkeypatch.setattr(auto_start, "analyze_work_item", analyze)
    return started


async def _item(db, env, key, *, source_type="servicenow", state="intake", table="incident", labels=()):
    db.add(WorkItem(id=str(uuid.uuid4()), project_id=env.workspace_id, source_type=source_type, source_instance="t",
                    source_key=key, title=key, work_state=state, issue_type=table, labels_json=list(labels),
                    imported_at=utc_now() - timedelta(hours=1)))
    await db.commit()


@pytest.mark.asyncio
async def test_new_servicenow_incidents_are_analysed_only_when_switched_on(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings=ON, source_type="servicenow")
    await _item(db, env, "INC0000103")
    await _item(db, env, "INC0000101", state="development")  # not new
    await _item(db, env, "CHG0000001", table="change_request")
    await _item(db, env, "INC0000104", state="done")  # closed
    started = _record(monkeypatch)
    summary = await auto_analyze_after_sync(db, project_id=env.workspace_id, source_type="servicenow", actor=env.user)
    assert sorted(key for key, _mode in started) == sorted([env.item.source_key, "INC0000103"])
    assert {mode for _key, mode in started} == {"auto"} and summary["started"] == 2
    off = await seed_env(db, monkeypatch, settings={"model_policy": f"{POLICY}@1"}, source_type="servicenow")
    started.clear()
    assert (await auto_analyze_after_sync(db, project_id=off.workspace_id, source_type="servicenow",
                                          actor=off.user))["started"] == 0 and started == []


@pytest.mark.asyncio
async def test_jira_items_need_the_label_case_insensitively(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings=ON)  # the seeded item carries "octryx"
    await _item(db, env, "BRD-90", source_type="jira", labels=["other"])
    started = _record(monkeypatch)
    await auto_analyze_after_sync(db, project_id=env.workspace_id, source_type="jira", actor=env.user)
    assert started == [(env.item.source_key, "auto")]


@pytest.mark.asyncio
async def test_one_sync_starts_a_bounded_number_and_skips_recent_runs(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings=ON, source_type="servicenow")
    for index in range(MAX_PER_SYNC + 2):
        await _item(db, env, f"INC10{index}")
    env.item.imported_at = utc_now()  # the newest item: without the skip it would take a slot
    await db.commit()
    started = _record(monkeypatch)

    async def recent(_db, item_id):
        return item_id == env.item.id

    monkeypatch.setattr(auto_start, "recent_auto_run", recent)
    summary = await auto_analyze_after_sync(db, project_id=env.workspace_id, source_type="servicenow", actor=env.user)
    assert summary["started"] == MAX_PER_SYNC and env.item.source_key not in {key for key, _ in started}


@pytest.mark.asyncio
async def test_a_failure_is_reported_and_never_raised(db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings=ON, source_type="servicenow")

    async def broken(*_args, **_kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(auto_start, "analyze_work_item", broken)
    summary = await auto_analyze_after_sync(db, project_id=env.workspace_id, source_type="servicenow", actor=env.user)
    assert summary == {"started": 0, "results": [], "error": "auto_analyze_failed"}
    assert await auto_analyze_after_sync(db, project_id=None, source_type="jira", actor=env.user) == {
        "started": 0, "results": []}


@pytest.mark.asyncio
async def test_the_scheduled_jira_sync_starts_the_automatic_analyses(db, monkeypatch):
    from app.services.secure_work.jira import jira_sync_task

    env = await seed_env(db, monkeypatch, settings=ON)
    config = WorkItemSyncConfig(id=str(uuid.uuid4()), name="BRD", project_id=env.workspace_id, source_type="jira",
                                created_by=env.user.id)
    db.add(config)
    await db.commit()

    async def synced(db, **_kwargs):
        return {"sync_run": {"id": "run-1", "summary": {"imported": 1}}}

    calls = []

    async def after_sync(db, *, project_id, source_type, actor):
        calls.append((project_id, source_type, actor.id))
        return {"started": 1, "results": []}

    monkeypatch.setattr(jira_sync_task, "run_jira_work_item_sync", synced)
    monkeypatch.setattr("app.services.work_item_analysis.auto_start.auto_analyze_after_sync", after_sync)
    task = SimpleNamespace(config={"sync_config_id": config.id}, owner_id=env.user.id)
    run = SimpleNamespace(output=None)
    output = await jira_sync_task.run_scheduled_jira_work_item_sync(db, task=task, task_run=run)
    assert calls == [(env.workspace_id, "jira", env.user.id)] and output["auto_analyze"]["started"] == 1
