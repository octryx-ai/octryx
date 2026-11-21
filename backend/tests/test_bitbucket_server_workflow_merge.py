"""A Bitbucket Server pull request a run opens is watched to its merge or decline.

The Server create tool answers the pull request's web URL as the string ``links`` (``_pr_summary``), with no
``url``. The run stores the identity derived from it on the run and on the Work Item's pull request record, so a
signed merge webhook or the poll's decline read resumes the run and marks the record for the refresh worker.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.services.secure_work.coding.coding_pr_delivery as pr_delivery
import app.tools.bitbucket_impl._bitbucket_pull_requests as bitbucket_prs
from app.models import BuiltInToolConfig, WorkPullRequest
from app.models.runtime.secure_work import WorkItem
from app.services.admin.project.named_connection_service import save_named
from app.services.workflow_runs import watch_events as events
from app.services.workflow_runs.watch import deliver_event, poll_watching_runs
from app.tools.context import ToolContext
from tests.agent_definition_revision_fixtures import make_project
from tests.test_workflow_run_platform_actions import FakeTools, _repository, _run
from tests.test_workflow_run_watch import _watching

HOST = "bitbucket.example.test"
PR_URL = f"https://{HOST}/projects/PAY/repos/payments/pull-requests/7"
BRANCH = "feature/PAY-1-totals"


def _server_pr(state: str = "OPEN", href: str = PR_URL) -> dict:
    """A pull request as the Bitbucket Server REST API answers it."""
    repository = {"slug": "payments", "project": {"key": "PAY"}}
    return {"id": 7, "version": 0, "title": "PAY-1: Totals", "state": state, "description": "PAY-1",
            "author": {"user": {"displayName": "Platform Bot"}},
            "fromRef": {"id": f"refs/heads/{BRANCH}", "displayId": BRANCH, "repository": repository},
            "toRef": {"id": "refs/heads/main", "displayId": "main", "repository": repository},
            "reviewers": [], "createdDate": 1700000000000, "updatedDate": 1700000000000,
            "links": {"self": [{"href": href}]}}


async def _created_by_the_server_tool(monkeypatch) -> dict:
    """The create tool's own answer for a newly opened Server pull request."""
    async def post(context, path, *, payload):
        return _server_pr(), 201

    async def none(*_args, **_kwargs):
        return None

    async def contract(db, **kwargs):
        return {"reviewers": list(kwargs["explicit_reviewers"] or []), "source": "explicit"}

    monkeypatch.setattr(bitbucket_prs, "require_project_repository_operation", none)
    monkeypatch.setattr(bitbucket_prs, "_is_repo_allowed", lambda *_args: True)
    monkeypatch.setattr(bitbucket_prs, "_find_open_pull_request_for_branch", none)
    monkeypatch.setattr(bitbucket_prs, "_bitbucket_json_post", post)
    monkeypatch.setattr(pr_delivery, "reviewer_contract_for_bitbucket_pr_tool", contract)
    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="s",
                          project_config={"bitbucket_url": f"https://{HOST}", "bitbucket_token": "t"})
    created = await bitbucket_prs.CreateBitbucketPullRequest().execute(
        {"project_key": "PAY", "repo_slug": "payments", "title": "PAY-1: Totals", "from_branch": BRANCH,
         "to_branch": "main", "reviewers": []}, context)
    assert created["status"] == "created" and created["links"] == PR_URL and "url" not in created
    return created


async def _server_run(db, monkeypatch):
    created = await _created_by_the_server_tool(monkeypatch)
    tools = FakeTools(monkeypatch, {"create_bitbucket_pull_request": [created]})
    project = await make_project(db)
    await _repository(db, project.id, "bitbucket", "payments", owners=[])
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=project.id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=project.id, actor_id=None, payload={
        "name": "Bitbucket-Server", "bound_scopes": ["PAY/payments"], "bitbucket_url": f"https://{HOST}",
        "bitbucket_auth_mode": "bearer_pat", "bitbucket_token": "t"})
    item = WorkItem(source_type="jira", source_instance="t", source_key=f"PAY-{uuid.uuid4().hex[:4]}",
                    title="Totals", project_id=project.id)
    db.add(item)
    await db.flush()
    run = await _run(db, _watching(["pr.merged", "pr.declined"], advance="auto"), work_item_id=item.id,
                     project_id=project.id, repository="bitbucket:PAY/payments", branch=BRANCH)
    return run, tools, project, item


async def _record(db, item: WorkItem) -> WorkPullRequest:
    return (await db.execute(select(WorkPullRequest).where(WorkPullRequest.work_item_id == item.id))).scalar_one()


def _identity_parts(row: WorkPullRequest) -> dict[str, str]:
    return {column: getattr(row, column) for column in ("provider", "provider_instance", "project_key",
                                                        "repository_slug", "pr_id")}


async def _opened_and_watching(db, monkeypatch):
    run, tools, project, item = await _server_run(db, monkeypatch)
    assert "create_bitbucket_pull_request" in tools.tools()
    assert (run.status, run.waiting_kind, run.current_node_id) == ("waiting", "watching", "watch"), run.context
    identity = {"provider": "bitbucket", "provider_instance": HOST, "project_key": "PAY",
                "repository_slug": "payments", "pr_id": "7"}
    assert run.pull_request["url"] == PR_URL and run.pull_request["identity"] == identity
    assert run.node_state["waiting"]["target"]["pr"] == identity
    record = await _record(db, item)
    assert _identity_parts(record) == identity and record.refresh_requested_at is None
    return run, tools, project, record


@pytest.mark.asyncio
async def test_a_signed_server_merge_resumes_the_run_and_requests_the_refresh(db, monkeypatch):
    run, _tools, project, record = await _opened_and_watching(db, monkeypatch)

    def merged(href: str) -> events.WatchEvent:
        pull = _server_pr("MERGED", href)
        return events.scm_event({"eventKey": "pr:merged", "pullRequest": pull}, {})

    # The same path and number on another host is another pull request.
    other = merged("https://bitbucket.other.test/projects/PAY/repos/payments/pull-requests/7")
    assert await deliver_event(db, other, source="webhook", project_id=project.id) == []
    assert record.refresh_requested_at is None

    assert await deliver_event(db, merged(PR_URL), source="webhook", project_id=project.id) == [run.id]
    assert (run.status, run.outcome) == ("completed", "done")
    assert record.refresh_requested_at is not None


@pytest.mark.asyncio
async def test_a_polled_server_decline_resumes_the_run_and_requests_the_refresh(db, monkeypatch):
    run, tools, _project, record = await _opened_and_watching(db, monkeypatch)
    tools.answers["get_bitbucket_pull_request"] = [bitbucket_prs._pr_summary(_server_pr("DECLINED"))]

    assert await poll_watching_runs(db) == 1
    assert tools.calls[-1][:2] == ("get_bitbucket_pull_request",
                                   {"project_key": "PAY", "repo_slug": "payments", "pr_id": "7"})
    assert (run.status, run.outcome) == ("completed", "blocked")
    assert record.refresh_requested_at is not None
