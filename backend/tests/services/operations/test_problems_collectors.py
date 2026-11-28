"""Problems aggregator (E5): each collector turns seeded status rows into problem, attention or nothing."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from app.models import (
    ConnectorHealth,
    ConnectorHealthLog,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
    LLMProvider,
)
from app.services.problems import connections, syncs
from app.services.problems.model import CollectContext
from tests.services.operations.problems_collectors_support import NOW, _by_object, _setup, uid


@pytest.mark.asyncio
async def test_connection_failing_series_degraded_stale_and_ok(db):
    project, _, ctx = await _setup(db)
    for name, status, checked in (("jira", "error", NOW), ("confluence", "degraded", NOW),
                                  ("stale", "error", NOW - timedelta(days=8)), ("fine", "ok", NOW)):
        db.add(ConnectorHealth(connector_name=name, project_id=project.id, status=status, last_checked=checked))
    for minutes, status in ((50, "error"), (40, "ok"), (30, "error"), (20, "error"), (10, "error")):
        db.add(ConnectorHealthLog(connector_name="jira", project_id=project.id, status=status,
                                  checked_at=NOW - timedelta(minutes=minutes)))
    await db.flush()

    problems = await connections.collect(db, ctx)

    jira = _by_object(problems, "jira")[0]
    assert (jira.severity, jira.count, jira.reason_code) == ("problem", 3, "check_failed")
    assert jira.since == NOW - timedelta(minutes=30) and jira.workspace_id == project.id
    assert jira.key == f"connection:jira@{project.id}:check_failed"
    # The connections page; no connection replaced this entry, so the list (no ``connection``).
    assert jira.fix["href"] == "/chat?area=admin&tab=adminConnections" and jira.connection_id is None
    assert _by_object(problems, "confluence")[0].severity == "attention"
    assert not _by_object(problems, "stale") and not _by_object(problems, "fine")


@pytest.mark.asyncio
async def test_provider_health_is_platform_wide_and_hidden_from_workspace_scopes(db):
    _, _, ctx = await _setup(db)
    down = LLMProvider(name="bedrock", driver="bedrock_api", display_name="Bedrock EU", is_active=True, is_global=True,
                       health_status="auth_denied", last_health_check_at=NOW)
    slow = LLMProvider(name="openrouter", driver="openrouter_api", display_name="OR", is_active=True, is_global=True,
                       health_status="no_models", last_health_check_at=NOW)
    ready = LLMProvider(name="ollama", driver="ollama", is_active=True, is_global=True, health_status="ok", last_health_check_at=NOW)
    db.add_all([down, slow, ready])
    await db.flush()

    everything = await connections.collect(db, CollectContext(now=NOW))
    item = _by_object(everything, down.id)[0]
    assert (item.severity, item.object_type, item.workspace_id) == ("problem", "provider", None)
    assert item.to_dict()["workspace"] is None
    assert _by_object(everything, slow.id)[0].severity == "attention" and not _by_object(everything, ready.id)
    assert not _by_object(await connections.collect(db, ctx), down.id)


@pytest.mark.asyncio
async def test_sync_failed_series_needs_configuration_overdue_and_healthy(db):
    project, _, ctx = await _setup(db)

    def connector(key: str, **extra) -> KnowledgeSourceConnector:
        return KnowledgeSourceConnector(id=uid(), project_id=project.id, connector_key=key, kind="jira", scope={},
                                        products=[], cursor={}, **extra)

    failing, config, healthy = connector("jira-a"), connector("jira-b"), connector("jira-c")
    overdue = connector("jira-d", schedule_enabled=True, schedule_interval_minutes=60,
                        next_scheduled_at=NOW - timedelta(hours=3))
    recent = connector("jira-e", schedule_enabled=True, schedule_interval_minutes=60,
                       next_scheduled_at=NOW - timedelta(minutes=90))
    db.add_all([failing, config, healthy, overdue, recent])
    await db.flush()
    for item, state, hours in ((failing, "completed", 5), (failing, "failed", 3), (failing, "failed", 1),
                               (config, "needs_configuration", 1), (healthy, "failed", 3),
                               (healthy, "completed", 1)):
        db.add(KnowledgeSourceSyncRun(connector_id=item.id, project_id=project.id, state=state,
                                      reason="auth_failed" if state == "failed" else None,
                                      started_at=NOW - timedelta(hours=hours)))
    await db.flush()

    problems = await syncs.collect(db, ctx)

    first = _by_object(problems, failing.id)[0]
    assert (first.severity, first.count, first.reason_code) == ("problem", 2, "auth_failed")
    assert first.since == NOW - timedelta(hours=3)
    assert f"source={failing.connector_key}" in first.fix["href"] and "tab=workspaceKnowledge" in first.fix["href"]
    assert _by_object(problems, config.id)[0].severity == "attention"
    assert _by_object(problems, overdue.id)[0].reason_code == "overdue"
    assert not _by_object(problems, healthy.id) and not _by_object(problems, recent.id)


@pytest.mark.asyncio
async def test_a_source_without_schedule_and_without_a_recent_sync_is_stale(db):
    project, _, ctx = await _setup(db)

    def connector(key: str, created_days: int, **extra) -> KnowledgeSourceConnector:
        return KnowledgeSourceConnector(id=uid(), project_id=project.id, connector_key=key, kind="confluence",
                                        scope={}, products=[], cursor={},
                                        created_at=NOW - timedelta(days=created_days), **extra)

    old, never, fresh, scheduled = (connector("rs-old", 40), connector("rs-never", 30), connector("rs-fresh", 40),
                                    connector("rs-sched", 40, schedule_enabled=True, schedule_interval_minutes=60,
                                              next_scheduled_at=NOW + timedelta(minutes=30)))
    failing = connector("rs-failing", 40)
    db.add_all([old, never, fresh, scheduled, failing])
    await db.flush()
    for item, state, days in ((old, "completed", 31), (fresh, "completed", 2), (scheduled, "completed", 20),
                              (failing, "completed", 30), (failing, "failed", 1)):
        db.add(KnowledgeSourceSyncRun(connector_id=item.id, project_id=project.id, state=state,
                                      reason="auth_failed" if state == "failed" else None,
                                      started_at=NOW - timedelta(days=days)))
    await db.flush()

    problems = await syncs.collect(db, ctx)

    stale = _by_object(problems, old.id)[0]
    assert (stale.severity, stale.reason_code) == ("attention", "stale") and "no schedule" in stale.title
    assert stale.title == "Knowledge source rs-old has not been synced for more than 14 days and has no schedule."
    assert _by_object(problems, never.id)[0].title == "Knowledge source rs-never has not been synced yet and has no schedule."
    assert stale.since == NOW - timedelta(days=31)
    assert _by_object(problems, never.id)[0].reason_code == "stale"
    assert not _by_object(problems, fresh.id) and not _by_object(problems, scheduled.id)
    assert [item.reason_code for item in _by_object(problems, failing.id)] == ["auth_failed"]  # failed, not stale


@pytest.mark.asyncio
async def test_a_launcher_snapshot_is_stale_by_its_last_upload_not_by_sync_runs(db):
    project, _, ctx = await _setup(db)

    def snapshot(key: str, uploaded_days: int | None) -> KnowledgeSourceConnector:
        cursor = {"last_pass_closed_at": (NOW - timedelta(days=uploaded_days)).isoformat()} if uploaded_days else {}
        return KnowledgeSourceConnector(
            id=uid(), project_id=project.id, connector_key=key, kind="git_repository", products=[], cursor=cursor,
            scope={"fetch_mode": "local_snapshot", "remote": f"https://git.example/{key}", "head_commit": "a" * 40},
            created_at=NOW - timedelta(days=60), updated_at=NOW - timedelta(days=50))

    old, recent, unknown = snapshot("repo-old", 20), snapshot("repo-recent", 3), snapshot("repo-unknown", None)
    db.add_all([old, recent, unknown])
    await db.flush()

    problems = await syncs.collect(db, ctx)

    stale = _by_object(problems, old.id)[0]
    assert (stale.severity, stale.reason_code) == ("attention", "stale")
    # Named as Knowledge › Sources lists it, no ISO date (the row's "Since" shows the upload).
    assert stale.object_name == "repo-old (aaaaaaa)"
    assert stale.title == ("Knowledge source repo-old (aaaaaaa) was last uploaded more than 14 days ago; upload a new "
                           "snapshot from the launcher to refresh it.")
    assert stale.since == NOW - timedelta(days=20)
    assert not _by_object(problems, recent.id)
    # Without a recorded pass the source's own last change is the upload time.
    unknown_problem = _by_object(problems, unknown.id)[0]
    assert "last uploaded" in unknown_problem.title and unknown_problem.since == NOW - timedelta(days=50)
    assert all(not re.search(r"\d{4}-\d{2}-\d{2}", item.title) for item in problems)
    assert all("has not been synced" not in item.title for item in problems)
