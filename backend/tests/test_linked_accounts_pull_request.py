"""The pull request asks the requester's linked account to review, an unresolved requester never blocks it, the retried step adds the reviewer after linking, an existing pull request is adopted and a deleted base branch falls back to the default branch."""

from __future__ import annotations

import pytest

from app.models import UserLinkedAccount
from app.services.workflow_runs import attention, views
from app.services.workflow_runs.platform import pr_details, scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from tests.linked_accounts_support import ACCOUNT, _cloud_run, _scripted
from tests.phased_workflow_fixtures import admin_user

pytestmark = pytest.mark.asyncio


async def test_an_unresolved_requester_never_blocks_the_pull_request(db, monkeypatch):
    admin = await admin_user(db)
    run = await _cloud_run(db, admin)
    calls = _scripted(monkeypatch, {"id": 7, "url": "https://bitbucket.org/acme/payments/pull-requests/7",
                                    "status": "created", "reviewers_unresolved": []})
    outcome = await scm.open_pr(db, run, {})
    assert outcome.ok, outcome.reason
    pr = dict(next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request"))
    assert pr["reviewers"] == [] and "requester" not in pr
    assert "Atlassian Cloud account is not linked" in pr["description"]
    assert (admin.display_name or admin.username) in pr["description"]
    assert (run.pull_request["reviewer_skipped"], run.pull_request["requester_platform"]) == (
        "requester_unresolved", "atlassian")
    notice = views.reviewer_notice(run)
    assert notice["link_account"] == "atlassian" and "Link your account to be added as reviewer" in notice["text"]
    items = await attention.inbox_items(db, admin.id)
    own = next(item for item in items if item["kind"] == "workflow_run_review_own_pr")
    assert "Link your account to be added as reviewer" in own["subtitle"]


async def test_after_linking_the_retried_step_adds_the_reviewer_or_applies_the_author_exception(db, monkeypatch):
    admin = await admin_user(db)
    db.add(UserLinkedAccount(user_id=admin.id, platform="atlassian", account_id=ACCOUNT))
    run = await _cloud_run(db, admin)
    calls = _scripted(monkeypatch, {"id": 8, "url": "https://bitbucket.org/acme/payments/pull-requests/8",
                                    "status": "created", "reviewers_unresolved": []})
    assert (await scm.open_pr(db, run, {})).ok
    pr = dict(next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request"))
    assert (pr["reviewers"], pr["requester"]) == ([ACCOUNT], ACCOUNT)
    assert "search_jira_users" not in [tool for tool, _ in calls]  # a linked account needs no email lookup
    assert run.pull_request["reviewers"] == [ACCOUNT] and "reviewer_skipped" not in run.pull_request

    author = await _cloud_run(db, admin)
    _scripted(monkeypatch, {"id": 9, "url": "https://bitbucket.org/acme/payments/pull-requests/9", "status": "created",
                            "reviewers_unresolved": [], "reviewer_skipped": "requester_is_author"})
    assert (await scm.open_pr(db, author, {})).ok
    assert (author.pull_request["reviewer_skipped"], author.pull_request["reviewers"]) == ("requester_is_author", [])

    unknown = await _cloud_run(db, admin)
    _scripted(monkeypatch, {"id": 10, "url": "https://bitbucket.org/acme/payments/pull-requests/10",
                            "status": "created", "reviewers_unresolved": [ACCOUNT]})
    assert (await scm.open_pr(db, unknown, {})).ok  # the SCM does not know the linked account: still not blocked
    assert unknown.pull_request["reviewer_skipped"] == "requester_unresolved"


async def test_a_pull_request_github_already_has_is_adopted_and_a_long_body_is_bounded(db, monkeypatch):
    """A restart between GitHub's create and the run's commit makes the retry create again; GitHub answers 422
    "A pull request already exists" and the step must not fail although the PR exists. And a body over GitHub's
    65,536 characters (review notes, open findings) is refused."""
    from app.services.workflow_runs.platform.dispatch import ToolOutcome

    admin = await admin_user(db)
    run = await _cloud_run(db, admin)
    run.repository, run.branch = "github:acme/payments", "feature/PAY-1-totals"
    calls: list[tuple[str, dict]] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        calls.append((tool, dict(arguments)))
        if tool == "create_github_pull_request":
            return ToolOutcome("failed", {"error": "Validation Failed: A pull request already exists for "
                                                   "acme:feature/PAY-1-totals."}, "A pull request already exists")
        if tool == "list_github_pull_requests":
            return read_outcome({"pull_requests": [{"number": 41, "head_ref": "feature/PAY-1-totals",
                                                    "html_url": "https://github.com/acme/payments/pull/41"}]})
        return read_outcome({"status": "ok"})

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    monkeypatch.setattr(scm, "review_notes_text", lambda _run: "x" * 70_000)
    outcome = await scm.open_pr(db, run, {})
    assert outcome.ok, outcome.reason
    assert (run.pull_request["id"], run.pull_request["url"]) == ("41", "https://github.com/acme/payments/pull/41")
    listed = next(arguments for tool, arguments in calls if tool == "list_github_pull_requests")
    assert listed["head"] == "acme:feature/PAY-1-totals"
    body = next(arguments for tool, arguments in calls if tool == "create_github_pull_request")["description"]
    assert len(body) <= pr_details.MAX_PR_DESCRIPTION and "Shortened" in body


async def test_a_story_whose_base_branch_was_deleted_starts_from_the_default_branch(db, monkeypatch):
    """When the story before was merged and GitHub deleted its branch, creating the next story's branch from it
    answers 404; the epic chain must not stop."""
    from app.services.workflow_runs.platform.dispatch import ToolOutcome

    admin = await admin_user(db)
    run = await _cloud_run(db, admin)
    run.repository, run.branch = "github:acme/payments", None
    run.context = {"base_branch": "feature/PAY-0-before"}
    calls: list[tuple[str, dict]] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        calls.append((tool, dict(arguments)))
        if tool == "create_github_branch" and arguments.get("start_point"):
            return ToolOutcome("failed", {"error": "GitHub API 404: Not Found"}, "Not Found")
        if tool == "create_github_branch":
            return read_outcome({"status": "created"})
        return ToolOutcome("failed", {}, "stop here")  # the prepare step is not part of this test

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    await scm.create_branch(db, run, {})
    branches = [arguments for tool, arguments in calls if tool == "create_github_branch"]
    assert [item.get("start_point") for item in branches] == ["feature/PAY-0-before", None]
    assert "base_branch" not in run.context and run.context.get("branch_created")
