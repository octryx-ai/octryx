"""Trust metrics: a run's merged pull request and a later revert of it, read from the provider's revert
description, recorded as a ``pr_reverted`` event and counted from that event."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRun, WorkflowRunEvent
from app.services.observability import agent_metrics, maintenance_metrics
from app.services.secure_work.pull_requests.record_identity import pull_request_identity
from app.services.workflow_runs.watch import EVENT_PR_REVERTED, deliver_event
from app.services.workflow_runs.watch_events import PR_MERGED, scm_event
from tests.observability_support import admin_user, workspace


@pytest.fixture(autouse=True)
def _empty_metrics():
    agent_metrics.reset()
    yield
    agent_metrics.reset()


def _github(number: int, *, title: str, body: str = "", branch: str = "feature") -> dict:
    return {"action": "closed", "repository": {"full_name": "acme/shop"},
            "pull_request": {"number": number, "merged": True, "title": title, "body": body, "head": {"ref": branch},
                             "html_url": f"https://github.com/acme/shop/pull/{number}"}}


def _opened(repository: str, number: str, host: str = "github.com") -> dict:
    url = f"https://{host}/{repository}/pull/{number}"
    return {"provider": "github", "repository": repository, "id": number, "url": url,
            "identity": pull_request_identity("github", url, repository, number)}


def test_each_providers_revert_button_is_recognised_and_a_plain_merge_is_none():
    github = scm_event(_github(31, title='Revert "Pay with cards"', body="Reverts acme/shop#12"),
                       {"X-GitHub-Event": "pull_request"})
    assert (github.condition, github.pr_id, github.reverts) == (PR_MERGED, "31", "12")
    by_branch = scm_event(_github(32, title='Revert "Pay with cards"', branch="revert-12-pay-cards"),
                          {"X-GitHub-Event": "pull_request"})
    assert by_branch.reverts == "12"
    gitlab = scm_event({"object_kind": "merge_request", "project": {"path_with_namespace": "acme/shop"},
                        "object_attributes": {"action": "merge", "iid": 8, "title": 'Revert "Pay"',
                                              "description": "This reverts merge request !5"}}, {})
    assert gitlab.reverts == "5"
    cloud = scm_event({"repository": {"full_name": "acme/shop"},
                       "pullrequest": {"id": 9, "title": "Revert pay", "source": {"branch": {"name": "revert-pr-4"}}}},
                      {"X-Event-Key": "pullrequest:fulfilled"})
    assert cloud.reverts == "4"
    plain = scm_event(_github(33, title="Revert-proof checkout", branch="revert-handling"),
                      {"X-GitHub-Event": "pull_request"})
    assert plain.reverts == ""


@pytest.mark.asyncio
async def test_a_revert_merge_marks_the_reverted_runs_pull_request_and_counts_it(db):
    admin = await admin_user(db)
    project = await workspace(db, "Shop")
    reverted = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="story-delivery", title="Pay",
                           requested_by=admin.id, status="completed",
                           pull_request=_opened("acme/shop", "12"))
    other = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="story-delivery", title="Ship",
                        requested_by=admin.id, status="completed",
                        pull_request=_opened("acme/other", "12"))
    other_host = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="story-delivery",
                             title="Elsewhere", requested_by=admin.id, status="completed",
                             pull_request=_opened("acme/shop", "12", host="ghe.example.test"))
    db.add_all([reverted, other, other_host])
    await db.commit()

    event = scm_event(_github(31, title='Revert "Pay"', body="Reverts acme/shop#12"), {"X-GitHub-Event": "pull_request"})
    await deliver_event(db, event, source="github", project_id=project.id)
    await db.commit()

    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.kind == EVENT_PR_REVERTED))).scalars()
    assert [(row.run_id, row.detail["revert_pr"]) for row in events] == [(reverted.id, "31")]
    assert maintenance_metrics.PRS_REVERTED.series == {("story-delivery",): 1}


def test_a_merged_pull_request_counts_once_whether_or_not_the_run_is_in_memory():
    class Run:
        context: dict = {}

    for run in (None, Run()):
        counted = maintenance_metrics.run_event("story-delivery", "r1", "watch_condition_met",
                                                {"condition": "pr.merged"}, run=run)
        counted()
    assert maintenance_metrics.PRS_MERGED.series == {("story-delivery",): 2}
