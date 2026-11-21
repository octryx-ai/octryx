"""Recorded pull requests are read from their host.

Fake hosts only (no network): the state mapping per host, merged detection, a failed read keeps the last status,
the periodic pass picks due open PRs (and requested ones) only, a workflow watch that saw the PR merged requests the
refresh of the run's own record (its Work Item's Workspace only), and a stored profile reference the record's
Workspace no longer admits is removed, never used (scoped loader).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, WorkItem, WorkRepositoryProfile
from app.services.secure_work.pull_requests import refresh
from app.services.secure_work.pull_requests.host_clients import HostRead
from app.services.secure_work.pull_requests.host_state import HostPullRequest, HostStateError
from app.services.secure_work.pull_requests.host_target import HostTarget, PullRequestHostError
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.time_utils import utc_now
from tests.work_pull_request_refresh_support import _admin, _pr


class FakeHost:
    def __init__(self) -> None:
        self.read_result: HostRead | Exception = HostRead(HostPullRequest(status="open"))
        self.reads = 0

    async def read(self, target):
        self.reads += 1
        if isinstance(self.read_result, Exception):
            raise self.read_result
        return self.read_result


@pytest.fixture
def host(monkeypatch):
    fake = FakeHost()

    async def target(db, row):
        return HostTarget(row.provider, "bitbucket_server", "OCX", "runtime", row.pr_id, None, "conn-1",
                          SimpleNamespace())

    monkeypatch.setattr(refresh, "resolve_target", target)
    monkeypatch.setattr(refresh, "client_for", lambda target: fake)
    return fake


def _merged(**extra) -> HostRead:
    return HostRead(HostPullRequest(
        status="merged", title="OCX-1: done", source_updated_at=datetime(2026, 11, 5, 9, 0),
        reviewers=[{"username": "alice", "name": "Alice", "approval": "approved"}], host_state="MERGED"), **extra)


# --- refresh service -----------------------------------------------------------------------------------------


async def test_refresh_detects_merged_and_stores_reviewers_build_and_sync_time(db, host):
    row = await _pr(db)
    before = row.last_synced_at
    host.read_result = _merged(build_status="successful")
    outcome = await refresh.refresh_pull_request(db, row, source="requested")
    assert outcome["ok"] and outcome["previous_status"] == "open"
    assert row.status == "merged" and row.refresh_status == "ok" and row.refresh_error_code is None
    assert row.approvals_json == [{"username": "alice", "name": "Alice", "approval": "approved"}]
    assert row.build_status == "successful" and row.source_updated_at == datetime(2026, 11, 5, 9, 0)
    assert row.last_synced_at >= before and row.raw_summary_json["host"]["connection_id"] == "conn-1"


@pytest.mark.parametrize(("error", "code"), [
    (PullRequestHostError("connection_refused", "no connection"), "connection_refused"),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://h"),
                           response=httpx.Response(403)), "host_permission"),
    (httpx.ConnectError("down"), "host_unavailable"),
    (HostStateError("unknown_host_state", "odd"), "unknown_host_state"),
])
async def test_a_failed_read_keeps_the_last_status_and_records_the_code(db, host, error, code):
    row = await _pr(db, build_status="successful")
    synced = row.last_synced_at
    host.read_result = error
    outcome = await refresh.refresh_pull_request(db, row, source="periodic")
    assert not outcome["ok"] and outcome["error_code"] == code
    assert row.status == "open" and row.build_status == "successful" and row.last_synced_at == synced
    assert row.refresh_status == "failed" and row.refresh_error_code == code and row.refresh_attempted_at


async def test_a_failed_build_read_is_partial_and_keeps_the_build_status(db, host):
    row = await _pr(db, build_status="failed")
    host.read_result = _merged(build_error=PullRequestHostError("host_unavailable", "build down"))
    await refresh.refresh_pull_request(db, row, source="periodic")
    assert row.status == "merged" and row.build_status == "failed"
    assert row.refresh_status == "partial" and row.refresh_error_code == "host_unavailable"


async def test_periodic_pass_picks_due_open_and_requested_rows_only(db, host):
    due = await _pr(db, number="1")
    recent = await _pr(db, number="2", refresh_attempted_at=utc_now() - timedelta(minutes=2))
    stale = await _pr(db, number="3", refresh_attempted_at=utc_now() - timedelta(minutes=20))
    merged = await _pr(db, number="4", status="merged")
    gitlab = await _pr(db, number="5", provider="gitlab")
    requested = await _pr(db, number="6", status="merged", refresh_requested_at=utc_now())
    picked = set((await db.execute(refresh.due_pull_requests_query())).scalars().all())
    assert picked == {due.id, stale.id, requested.id}
    assert {recent.id, merged.id, gitlab.id}.isdisjoint(picked)
    host.read_result = _merged()
    counts = await refresh.sweep_pull_requests(db)
    assert counts == {"refreshed": 3, "failed": 0} and host.reads == 3
    await db.refresh(requested)
    assert requested.refresh_requested_at is None
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "secure_work.pull_request_refreshed")))
    assert {a.details["source"] for a in audits.scalars().all()} >= {"periodic"}


async def _item(db, key: str) -> WorkItem:
    project = Project(name=f"ws-{key}", config={})
    db.add(project)
    await db.flush()
    item = WorkItem(project_id=project.id, source_type="jira", source_instance="refresh-test", source_key=key,
                    title=key, work_state="implementation", sync_state="imported")
    db.add(item)
    await db.commit()
    return item


async def test_a_watch_that_saw_the_pr_merged_requests_its_refresh(db, monkeypatch):
    from app.services.workflow_runs import watch
    from app.services.workflow_runs.states import STATUS_WAITING, WAITING_WATCH

    item, elsewhere = await _item(db, "OCX-1"), await _item(db, "OCX-2")
    row = await _pr(db, work_item_id=item.id, number="77")
    other = await _pr(db, work_item_id=item.id, number="78")
    same_pr_other_workspace = await _pr(db, work_item_id=elsewhere.id, number="77")
    node = SimpleNamespace(id="merged", config={"conditions": ["pr.merged", "pr.declined"], "advance": "confirm"})

    async def graph(db, run):
        return SimpleNamespace(nodes={"merged": node})

    monkeypatch.setattr(watch, "graph_for_run", graph)
    monkeypatch.setattr(watch, "record_event", lambda *args, **kwargs: None)
    run = SimpleNamespace(status=STATUS_WAITING, waiting_kind=WAITING_WATCH, current_node_id="merged", context={},
                          node_state={}, ticket_key="OCX-1", branch="feature/OCX-1", work_item_id=item.id,
                          project_id=item.project_id,
                          pull_request={"provider": "bitbucket", "repository": "OCX/runtime", "id": "77",
                                        "identity": pull_request_identity("bitbucket", row.pr_url, "OCX/runtime", "77")})
    assert await watch.record_condition(db, run, "pr.merged", source="poll")
    await db.commit()
    for refreshed in (row, other, same_pr_other_workspace):
        await db.refresh(refreshed)
    assert row.refresh_requested_at is not None and other.refresh_requested_at is None
    assert same_pr_other_workspace.refresh_requested_at is None  # the run's Workspace only
    assert row.id in set((await db.execute(refresh.due_pull_requests_query())).scalars().all())


@pytest.mark.parametrize("profile_workspace", ["own", "global", "foreign"])
async def test_a_stored_profile_reference_is_read_through_the_scoped_loader(db, host, profile_workspace):
    item, elsewhere = await _item(db, "OCX-5"), await _item(db, "OCX-6")
    project_id = {"own": item.project_id, "global": None, "foreign": elsewhere.project_id}[profile_workspace]
    profile = WorkRepositoryProfile(name="runtime", project_id=project_id, provider="bitbucket",
                                    pr_target_branch="release", created_by=(await _admin(db)).id)
    db.add(profile)
    await db.commit()
    row = await _pr(db, work_item_id=item.id, target_branch="main", repository_profile_id=profile.id)
    host.read_result = HostRead(HostPullRequest(status="open", target_branch="main"))
    await refresh.refresh_pull_request(db, row, source="periodic")
    kinds = {entry["type"] for entry in row.mismatch_json}
    if profile_workspace == "foreign":  # the reference no longer fits the item's Workspace: removed, not used
        assert row.repository_profile_id is None and "wrong_target_branch" not in kinds
    else:
        assert row.repository_profile_id == profile.id and "wrong_target_branch" in kinds
