"""Contract: the internal pull request record, its refresh and the reviewer recommendation stay in the
Workspace the run or coding session resolved."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    Project,
    User,
    WorkItem,
    WorkItemChangeUnit,
    WorkPullRequest,
    WorkRepositoryProfile,
)
from app.services.secure_work.pull_requests import host_target, refresh
from app.services.secure_work.pull_requests.host_target import PullRequestHostError, resolve_target
from app.services.secure_work.pull_requests.pull_requests import detect_mismatches, find_record, sync_pull_request
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.secure_work.reviewers import recommend_reviewers_for_work_item
from app.services.workflow_runs.platform import pr_details
from app.services.workflow_runs.platform.dispatch import SUCCEEDED, ToolOutcome
from app.services.workflow_runs.platform.pr_reviewers import PrReviewers
from app.services.workflow_runs.platform.repo_ref import RepoRef

PR_URL = "https://scm.example.test/projects/OCX/repos/runtime/pull-requests/77"
IDENTITY = pull_request_identity("bitbucket", PR_URL, "OCX/runtime", "77")


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _item(db) -> WorkItem:
    project = Project(name=f"ws-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    item = WorkItem(project_id=project.id, source_type="jira", source_instance="pr-scope",
                    source_key=f"OCX-{uuid.uuid4().hex[:6]}", title="t", work_state="implementation",
                    sync_state="imported")
    db.add(item)
    await db.commit()
    return item


def _payload(item: WorkItem, **extra) -> dict:
    return {"work_item_id": item.id, "identity": IDENTITY, "pr_url": PR_URL, "title": "own", "status": "open", **extra}


async def _record(db, item: WorkItem, *, scope_key: str | None = None, **columns) -> WorkPullRequest:
    values = {**IDENTITY, "title": "foreign", "status": "open", **columns}
    row = WorkPullRequest(work_item_id=item.id, scope_key=scope_key or item.project_id, created_by=(await _admin(db)).id,
                          pr_url=PR_URL, **values)
    db.add(row)
    await db.commit()
    return row


async def _rows(db) -> list[WorkPullRequest]:
    return list((await db.execute(select(WorkPullRequest))).scalars())


def _run(item: WorkItem, project_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(work_item_id=item.id, project_id=project_id or item.project_id,
                           pull_request={"provider": "bitbucket", "repository": "OCX/runtime", "id": "77",
                                         "identity": IDENTITY})


async def test_the_record_requires_the_resolved_workspace_on_its_item(db):
    own, foreign = await _item(db), await _item(db)
    for workspace_id in (own.project_id, None):
        with pytest.raises(HTTPException) as refused:
            await sync_pull_request(db, current_user=await _admin(db), workspace_id=workspace_id,
                                    payload=_payload(foreign))
        assert (refused.value.status_code, refused.value.detail) == (404, "Work Item not found")
    assert await _rows(db) == []


async def test_a_colliding_record_of_another_workspace_is_never_read_or_touched(db):
    own, foreign = await _item(db), await _item(db)
    theirs = await _record(db, foreign)
    created = await sync_pull_request(db, current_user=await _admin(db), workspace_id=own.project_id,
                                      payload=_payload(own))
    assert created["created"] is True and created["id"] != theirs.id
    mine = await db.get(WorkPullRequest, created["id"])
    assert (mine.scope_key, mine.work_item_id, mine.title) == (own.project_id, own.id, "own")
    assert await refresh.request_refresh_for_run(db, _run(own)) == 1
    await db.commit()
    await db.refresh(theirs)
    assert (theirs.title, theirs.updated_by, theirs.refresh_requested_at) == ("foreign", None, None)
    assert mine.refresh_requested_at is not None


async def test_a_change_unit_of_another_item_is_refused(db):
    own, foreign = await _item(db), await _item(db)
    unit = WorkItemChangeUnit(work_item_id=foreign.id, repository_name="runtime", branch_name="b",
                              created_by=(await _admin(db)).id)
    db.add(unit)
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await sync_pull_request(db, current_user=await _admin(db), workspace_id=own.project_id,
                                payload=_payload(own, change_unit_id=unit.id))
    assert (refused.value.status_code, refused.value.detail) == (404, "Change Unit not found for this Work Item")
    assert await _rows(db) == []


OPENED = [  # (provider, the URL the provider answered with, the run's repository path)
    ("github", "https://github.com/acme/runtime/pull/7", "acme/runtime"),
    ("github", "https://ghe.example.test/acme/runtime/pull/7", "acme/runtime"),  # another host
    ("github", "https://github.com/other/runtime/pull/7", "other/runtime"),  # another owner, same repository name
    ("bitbucket", "https://scm-a.example.test/projects/OCX/repos/runtime/pull-requests/7", "OCX/runtime"),
    ("bitbucket", "https://scm-b.example.test/projects/OCX/repos/runtime/pull-requests/7", "OCX/runtime"),
]


async def test_two_hosts_and_two_owners_of_a_same_named_repository_stay_distinct(db, monkeypatch):
    async def no_work_state(*args, **kwargs):
        return None

    monkeypatch.setattr(pr_details.pr_work_state, "pull_request_opened", no_work_state)
    item = await _item(db)
    admin = await _admin(db)
    runs = []
    for index, (provider, url, path) in enumerate(OPENED):
        run = SimpleNamespace(id=f"run-{index}", requested_by=admin.id, project_id=item.project_id,
                              work_item_id=item.id, branch="feature/x", current_node_id="pr", pull_request={})
        await pr_details._record_opened(db, run, RepoRef(provider, path), PrReviewers("", (), provider),
                                        ToolOutcome(SUCCEEDED, {"number": 7, "html_url": url}), item, "t")
        runs.append(run)
    await db.commit()
    rows = await _rows(db)
    assert sorted((row.provider, row.provider_instance, row.project_key, row.repository_slug, row.pr_id)
                  for row in rows) == sorted([
        ("github", "github.com", "acme", "runtime", "7"), ("github", "ghe.example.test", "acme", "runtime", "7"),
        ("github", "github.com", "other", "runtime", "7"), ("bitbucket", "scm-a.example.test", "OCX", "runtime", "7"),
        ("bitbucket", "scm-b.example.test", "OCX", "runtime", "7")])
    by_identity = {tuple(sorted(run.pull_request["identity"].items())): run for run in runs}
    assert len(by_identity) == len(OPENED)  # the run stores the identity it derived
    for run in runs:  # each run marks exactly the record it wrote
        assert await refresh.request_refresh_for_run(db, run) == 1
        await db.commit()
        marked = [row for row in await _rows(db) if row.refresh_requested_at is not None]
        assert [(row.provider_instance, row.project_key) for row in marked] == [
            (run.pull_request["identity"]["provider_instance"], run.pull_request["identity"]["project_key"])]
        for row in marked:
            row.refresh_requested_at = None
        await db.commit()




async def test_the_refresh_reads_only_through_a_connection_on_the_recorded_host(db, monkeypatch):
    item = await _item(db)
    row = await _record(db, item)
    elsewhere = await _record(db, item, provider_instance="scm-b.example.test")  # same path and number, other host
    served = {"bitbucket_url": "https://other.example.test", "bitbucket_allowed_repos": ["OCX/runtime"]}

    async def connection(*args, **kwargs):
        return SimpleNamespace(config=served, connection_id="conn-1")

    monkeypatch.setattr(host_target, "service_connection_config", connection)
    with pytest.raises(PullRequestHostError) as refused:
        await resolve_target(db, row)
    assert refused.value.code == "host_mismatch"
    served["bitbucket_url"] = "https://scm.example.test"
    assert (await resolve_target(db, row)).connection_id == "conn-1"
    # The worker's read of the other host's record through the same route stops before any host call.
    outcome = await refresh.refresh_pull_request(db, elsewhere, source="periodic")
    assert (outcome["ok"], outcome["error_code"], elsewhere.refresh_error_code) == (False, "host_mismatch",
                                                                                     "host_mismatch")


async def test_a_run_requests_the_refresh_of_its_exact_record_only(db):
    own = await _item(db)
    exact = await _record(db, own)
    other_project = await _record(db, own, project_key="OPS")  # same slug and number, another project
    other_host = await _record(db, own, provider_instance="second.example.test")
    other_item = await _item(db)
    assert await refresh.request_refresh_for_run(db, _run(own)) == 1
    # A run whose Workspace is not its item's marks nothing.
    assert await refresh.request_refresh_for_run(db, _run(own, project_id=other_item.project_id)) == 0
    await db.commit()
    for row in (exact, other_project, other_host):
        await db.refresh(row)
    assert exact.refresh_requested_at is not None
    assert other_project.refresh_requested_at is None and other_host.refresh_requested_at is None


async def test_the_worker_reads_only_records_bound_to_their_items_workspace(db):
    own, foreign = await _item(db), await _item(db)
    bound = await _record(db, own, pr_id="1")
    disagreeing = await _record(db, own, scope_key=foreign.project_id, pr_id="2")
    global_scope = await _record(db, own, scope_key="global", pr_id="3")
    due = set((await db.execute(refresh.due_pull_requests_query(batch=500))).scalars())
    assert bound.id in due and {disagreeing.id, global_scope.id}.isdisjoint(due)
    for row in (disagreeing, global_scope):
        with pytest.raises(PullRequestHostError) as refused:
            await resolve_target(db, row)
        assert refused.value.code == "record_out_of_scope"


async def test_the_mismatch_check_ignores_a_unit_of_another_item(db):
    own, foreign = await _item(db), await _item(db)
    unit = WorkItemChangeUnit(work_item_id=foreign.id, repository_name="runtime", branch_name="b",
                              reviewer_policy_json={"target_branch": "release", "required_reviewers": ["x"]},
                              created_by=(await _admin(db)).id)
    db.add(unit)
    await db.commit()
    row = await _record(db, own, change_unit_id=unit.id, target_branch="main")
    assert await detect_mismatches(db, row, None) == []


async def test_every_reader_and_the_writer_share_the_item_workspace_predicate(db):
    from app.services.secure_work.coding.coding_sessions import list_coding_session_candidates
    from app.services.secure_work.external_activity_matching import _candidate_pull_requests
    from app.services.secure_work.work_item_lifecycle import get_work_item_lifecycle

    own, foreign = await _item(db), await _item(db)
    bound = await _record(db, own, pr_id="1")
    unbound = await _record(db, own, scope_key=foreign.project_id, pr_id="2")  # never written; defense in depth
    lifecycle = await get_work_item_lifecycle(db, own.id)
    assert [pr["id"] for pr in lifecycle["pull_requests"]] == [bound.id]
    inventory = await list_coding_session_candidates(db, project_scope={own.project_id})
    assert [pr["id"] for entry in inventory["items"] for pr in entry["pull_requests"]] == [bound.id]
    assert [row.id for row in await _candidate_pull_requests(db, [own])] == [bound.id]
    identity = {column: getattr(unbound, column) for column in IDENTITY}
    assert await find_record(db, scope_key=foreign.project_id, identity=identity) is None


async def test_the_recommendation_reads_only_within_the_resolved_workspace(db):
    own, foreign = await _item(db), await _item(db)
    admin = await _admin(db)
    with pytest.raises(HTTPException) as refused:
        await recommend_reviewers_for_work_item(db, foreign.id, viewer=admin, workspace_id=own.project_id)
    assert refused.value.status_code == 404
    mine = WorkRepositoryProfile(name="runtime", project_id=own.project_id, created_by=admin.id,
                                 default_reviewers_json=["own.reviewer"])
    theirs = WorkRepositoryProfile(name="runtime", project_id=foreign.project_id, created_by=admin.id,
                                   default_reviewers_json=["foreign.reviewer"], owners_json=["Foreign team"])
    db.add_all([mine, theirs])
    await db.flush()
    db.add_all([WorkItemChangeUnit(work_item_id=own.id, repository_profile_id=profile.id, repository_name="runtime",
                                   branch_name=f"b-{index}", created_by=admin.id)
                for index, profile in enumerate((mine, theirs))])
    await db.commit()
    result = await recommend_reviewers_for_work_item(db, own.id, viewer=admin, workspace_id=own.project_id)
    names = {entry["display_name"] for entry in result["recommendations"]}
    assert "own.reviewer" in names and not names & {"foreign.reviewer", "Foreign team"}


