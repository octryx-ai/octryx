"""Bitbucket Cloud CI is the pushed commit's build statuses, Cloud webhooks become watch events, scm.comment posts on the branch pull request, and the Jira account lookup by email is one exact match."""

from __future__ import annotations

import pytest

from app.services.inbound_alerts.signature import sign_body, verify_call
from app.services.workflow_runs import watch
from app.services.workflow_runs.platform import ci, scm_comment
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.watch_events import ci_event, scm_event
from app.tools.jira_impl._jira_user_email import matching_accounts
from tests.bitbucket_cloud_workflow_support import EMAIL, HEAD, _run
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user


@pytest.mark.parametrize(("states", "expected"), [
    (["SUCCESSFUL"], "succeeded"), (["SUCCESSFUL", "STOPPED"], "failed"), (["INPROGRESS"], "running"), ([], "running"),
])
async def test_ci_is_the_build_statuses_of_the_pushed_commit(db, monkeypatch, states, expected) -> None:
    admin = await admin_user(db)
    calls: list[dict] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        calls.append({"tool": tool, **arguments})
        return read_outcome({"statuses": [{"state": state, "url": "https://bitbucket.org/p/1"} for state in states]})

    monkeypatch.setattr(ci, "dispatch_tool", dispatch)
    run = _run(await seed_workspace(db), admin.id, )
    run.context = {"head_sha": HEAD}
    result = await ci.read_ci_status(db, run, {})
    assert (result.provider, result.state, result.sha) == ("bitbucket", expected, HEAD)
    assert calls == [{"tool": "get_bitbucket_build_statuses", "project_key": "acme", "repo_slug": "payments",
                      "commit": HEAD, "include_test_reports": True}]  # a finished build's test reports with it


def test_cloud_webhooks_become_watch_events_and_one_success_never_passes_a_commit() -> None:
    def pr(key: str):
        return scm_event({"repository": {"full_name": "acme/payments"}, "pullrequest": {
            "id": 3, "links": {"html": {"href": "https://bitbucket.org/acme/payments/pull-requests/3"}}}},
                         {"X-Event-Key": key})

    assert (pr("pullrequest:fulfilled").condition, pr("pullrequest:rejected").condition,
            pr("pullrequest:approved").condition) == ("pr.merged", "pr.declined", "pr.approved")
    assert pr("pullrequest:updated") is None
    merged = pr("pullrequest:fulfilled")
    target = {"pr": {"provider": "bitbucket", "provider_instance": "bitbucket.org", "project_key": "acme",
                     "repository_slug": "payments", "pr_id": "3"},
              "repository": "bitbucket:acme/payments", "branch": "feature/PAY-1", "head_sha": HEAD}
    assert watch.matches(merged, target)

    def status(state: str, sha: str = HEAD):
        return ci_event({"repository": {"full_name": "acme/payments"}, "commit_status": {
            "state": state, "refname": "feature/PAY-1", "commit": {"hash": sha}}}, {"X-Event-Key": "repo:commit_status_updated"})

    assert status("INPROGRESS") is None
    assert not watch.matches(status("SUCCESSFUL"), target)
    assert watch.matches(status("FAILED"), target) and watch.matches(status("STOPPED"), target)
    assert not watch.matches(status("FAILED", "c" * 40), target)

    body = b'{"pullrequest": {"id": 3}}'
    headers = {"X-Hub-Signature": sign_body("hook-secret", body), "X-Request-UUID": "delivery-1"}
    first = verify_call(headers, body, "hook-secret", accept_untimestamped=True)
    other = verify_call({**headers, "X-Request-UUID": "delivery-2"}, body, "hook-secret", accept_untimestamped=True)
    assert first.method == "hmac" and first.delivery_key != other.delivery_key


async def test_scm_comment_posts_on_the_branch_pull_request_and_refuses_other_providers(db, monkeypatch) -> None:
    admin = await admin_user(db)
    sent: list[dict] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        sent.append({"tool": tool, "class": capability_class, **arguments})
        return read_outcome({"status": "created"})

    async def text(db_, run_, source):
        return f"text of {source}"

    monkeypatch.setattr(scm_comment, "dispatch_tool", dispatch)
    monkeypatch.setattr(scm_comment, "run_text", text)
    run = _run(await seed_workspace(db), admin.id)
    assert (await scm_comment.comment(db, run, {"text_from": "review"})).ok
    assert sent == [{"tool": "add_bitbucket_pull_request_comment", "class": "deliver", "project_key": "acme",
                     "repo_slug": "payments", "from_branch": run.branch, "text": "text of review"}]
    run.repository = "github:acme/payments"
    refused = await scm_comment.comment(db, run, {"text_from": "review"})
    assert not refused.ok and "github" in refused.reason and len(sent) == 1


def test_an_atlassian_account_by_email_is_one_exact_match_or_nothing() -> None:
    exact = {"accountId": "a1", "emailAddress": "Dev@Example.test", "accountType": "atlassian"}
    hidden = {"accountId": "a2", "accountType": "atlassian"}
    app = {"accountId": "a3", "accountType": "app", "emailAddress": EMAIL}
    assert matching_accounts([hidden, exact], EMAIL) == [exact]
    assert matching_accounts([hidden], EMAIL) == []  # a hidden address is never a match (review fix 3)
    assert matching_accounts([app], EMAIL) == []
    assert matching_accounts([{**exact, "emailAddress": "other@example.test"}], EMAIL) == []
